from __future__ import annotations

import os
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from image_to_cash.errors import ControlNotFound, FlowStopped, ManualReviewRequired, VerificationFailed
from image_to_cash.settings import Settings
from image_to_cash.ui import actions
from image_to_cash.ui.finder import Node, UiaNode, locate, preorder, resolve, scope_root
from image_to_cash.ui.locators import Locators, Scope, load_locators
from image_to_cash.ui.grid_ocr import (Grid, GridRow, capture_words, cell_span, cell_word, click_row, line_row,
                                       match_headers, ocr_words, read_cell_image, read_grid, row_at,
                                       visual_rows)
from image_to_cash.ui.waits import wait_stable, wait_until


def find_main_window() -> Any | None:
    from pywinauto import Desktop

    from image_to_cash.ui.discover import pick_fakturama_window

    own_pid = os.getpid()
    windows = [
        (w.window_text(), w.element_info.class_name, w)
        for w in Desktop(backend="uia").windows(visible_only=False)
        if w.process_id() != own_pid
    ]
    return pick_fakturama_window(windows)


def has_menu_bar(window: Any) -> bool:
    return any(c.control_type == "MenuBar" and c.name == "Application" for c in window.element_info.children())


def find_ready_main_window() -> Any | None:
    window = find_main_window()
    return window if window is not None and has_menu_bar(window) else None


START_PAGE = "Fakturama"


@dataclass(frozen=True)
class ProbeResult:
    screen: str
    control: str
    found: bool
    detail: str


def probe_tree(main: Node, locators: Locators, screens: list[str] | None = None) -> list[ProbeResult]:
    results = []
    for screen_name, screen in locators.screens.items():
        if screens and screen_name not in screens:
            continue
        try:
            root = scope_root(main, screen.scope)
        except ControlNotFound:
            continue
        for control_name, loc in screen.controls.items():
            try:
                node = resolve(root, loc)
            except ControlNotFound as exc:
                results.append(ProbeResult(screen_name, control_name, False, str(exc)))
                continue
            value = getattr(node, "value", None)
            detail = f"{node.control_type} {node.name!r} at {node.rect}"
            if value not in (None, ""):
                detail += f" value={value!r}"
            results.append(ProbeResult(screen_name, control_name, True, detail))
    return results


def format_probe(results: list[ProbeResult]) -> list[str]:
    lines, current = [], None
    for r in results:
        if r.screen != current:
            current = r.screen
            found = sum(1 for x in results if x.screen == current and x.found)
            total = sum(1 for x in results if x.screen == current)
            lines.append(f"{current}: {found}/{total} found")
        lines.append(f"  {'ok ' if r.found else '-- '} {r.control:22s} {r.detail}")
    return lines


class Fakturama:
    def __init__(self, window: Any, locators: Locators, settings: Settings):
        self.window = window
        self.locators = locators
        self.settings = settings

    @classmethod
    def connect(cls, settings: Settings, locators: Locators | None = None) -> "Fakturama":
        locators = locators or load_locators(settings.locators_file)
        if find_main_window() is None:
            if not settings.fakturama_exe:
                raise FlowStopped("Fakturama is not running. Start it and wait for its main window, "
                                  "or set FAKTURAMA_EXE in .env so it can be started automatically.")
            exe = Path(settings.fakturama_exe)
            if not exe.is_file():
                raise FlowStopped(f"FAKTURAMA_EXE does not point to a file: {exe}")
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        window = wait_until(find_ready_main_window, timeout=settings.startup_timeout,
                            what="Fakturama's main window and its menu bar")
        if window.is_minimized():
            window.restore()
        return cls(window, locators, settings)

    @property
    def pid(self) -> int:
        return self.window.process_id()

    @property
    def title(self) -> str:
        return self.window.window_text()

    def root(self) -> UiaNode:
        return UiaNode(self.window.element_info)

    def scope(self, screen: str, title: str | None = None) -> Scope:
        if title is None:
            return self.locators.screen(screen).scope
        return Scope(tab=r"\*?" + re.escape(title))

    def find(self, screen: str, control: str, title: str | None = None) -> UiaNode:
        return locate(self.root(), self.locators, screen, control, self.scope(screen, title))

    def is_open(self, screen: str, title: str | None = None) -> bool:
        try:
            scope_root(self.root(), self.scope(screen, title))
            return True
        except ControlNotFound:
            return False

    def editor_tabs(self, screen: str, title: str | None = None) -> list[UiaNode]:
        scope = self.scope(screen, title)
        if scope.tab is None:
            return []
        return [n for n in preorder(self.root())
                if n.control_type == "TabItem" and n.visible and re.fullmatch(scope.tab, n.name)]

    def editor_tab_names(self) -> list[str]:
        for tab in preorder(self.root()):
            if tab.control_type != "Tab":
                continue
            names = [c.name for c in tab.children() if c.control_type == "TabItem"]
            if START_PAGE in names:
                return [n for n in names if n != START_PAGE]
        return []

    def dialogs(self) -> list[actions.DialogInfo]:
        return [actions.dialog_info(d) for d in actions.open_dialogs(self.root())]

    def check_no_dialog(self, doing: str) -> None:
        shown = self.dialogs()
        if shown:
            first = shown[0]
            text = " ".join(" ".join(first.texts).split())
            raise ManualReviewRequired(f"Fakturama showed {first.title!r} while {doing}: {text}")

    def screenshot(self, path: str | Path) -> None:
        self.bring_to_front()
        self.window.capture_as_image().save(str(path))

    def editor_open(self, screen: str, title: str | None = None) -> bool:
        return self.is_open(screen, title) or bool(self.editor_tabs(screen, title))

    def activate(self, screen: str, title: str | None = None, timeout: float | None = None) -> UiaNode:
        if self.is_open(screen, title):
            return self.wait_open(screen, timeout, title)
        tabs = self.editor_tabs(screen, title)
        if not tabs:
            raise ControlNotFound(f"no open {screen} ({self.scope(screen, title).describe()})")
        if len(tabs) > 1:
            raise ManualReviewRequired(f"{len(tabs)} tabs named {tabs[0].name!r} are open; close the extra ones")
        actions.select_tab(tabs[0])
        return self.wait_open(screen, timeout, title)

    def wait_open(self, screen: str, timeout: float | None = None, title: str | None = None) -> UiaNode:
        scope = self.scope(screen, title)
        return wait_until(lambda: scope_root(self.root(), scope),
                          timeout=timeout or self.settings.ui_timeout, what=f"screen {screen} ({scope.describe()})")

    def wait_closed(self, screen: str, timeout: float | None = None, title: str | None = None) -> None:
        wait_until(lambda: not self.is_open(screen, title),
                   timeout=timeout or self.settings.ui_timeout, what=f"screen {screen} to close")

    def wait_for(self, screen: str, control: str, timeout: float | None = None, title: str | None = None) -> UiaNode:
        return wait_until(lambda: self.find(screen, control, title),
                          timeout=timeout or self.settings.ui_timeout, what=f"{screen}.{control}")

    def bring_to_front(self) -> None:
        if self.window.is_minimized():
            self.window.restore()
        self.window.set_focus()
        time.sleep(0.2)

    def maximize(self) -> None:
        if not self.window.is_maximized():
            self.window.maximize()

    def probe(self, screens: list[str] | None = None) -> list[ProbeResult]:
        return probe_tree(self.root(), self.locators, screens)

    def read(self, screen: str, control: str, title: str | None = None) -> str:
        return actions.read_value(self.find(screen, control, title))

    def click(self, screen: str, control: str, title: str | None = None) -> None:
        actions.click(self.find(screen, control, title))

    def click_when(self, screen: str, control: str, title: str | None = None, timeout: float | None = None) -> None:
        actions.click(self.wait_for(screen, control, timeout, title))

    def options(self, screen: str, control: str, title: str | None = None) -> list[str]:
        return actions.combo_options(self.find(screen, control, title))

    def save(self, screen: str, title: str | None = None, *, saved_title: str | None = None,
             timeout: float | None = None) -> str:
        timeout = timeout or self.settings.ui_timeout
        tab = self.activate(screen, title=title)
        before = tab.name
        item = next((c for c in tab.children() if c.control_type == "TabItem" and c.name == before), None)
        if item is None:
            raise ControlNotFound(f"no tab named {before!r} to save")
        self.bring_to_front()
        actions.ensure_foreground(item)
        item.wrapper().click_input()
        wait_until(lambda: self.find("main", "save").enabled, timeout=5, what="the toolbar Save button to be enabled")
        names = {saved_title, actions.editor_title(before)} - {None}
        others = [n for n in self.editor_tab_names() if n != before]
        actions.click(self.find("main", "save"))

        def saved_or_asked():
            tabs = self.editor_tab_names()
            for name in names:
                if name in tabs and f"*{name}" not in tabs:
                    return name
            if before not in tabs:
                renamed = [n for n in tabs if n not in others and not actions.is_dirty(n)]
                if len(renamed) == 1:
                    return renamed[0]
            dialogs = actions.open_dialogs(self.root())
            return dialogs[0] if dialogs else None

        outcome = wait_until(saved_or_asked, timeout=timeout, what=f"{before!r} to be saved")
        if isinstance(outcome, str):
            return outcome
        raise ManualReviewRequired(f"Fakturama showed a dialog while saving {before!r}: {actions.dialog_info(outcome)}")

    def type(self, screen: str, control: str, text: str, *, check: Any = None, commit: str = "{TAB}",
             title: str | None = None) -> str:
        return actions.set_text(self.find(screen, control, title), text, check=check, commit=commit)

    def exists(self, screen: str, control: str, title: str | None = None) -> bool:
        try:
            self.find(screen, control, title)
            return True
        except ControlNotFound:
            return False

    def read_table(self, screen: str, control: str, title: str | None = None,
                   required: tuple[str, ...] | None = None) -> Grid:
        columns = self.locators.control(screen, control).columns
        self.park_mouse()
        return read_grid(self.find(screen, control, title), columns, required=required,
                         lang=self.settings.ocr_language)

    def search_table(self, screen: str, text: str, timeout: float | None = None) -> Grid | None:
        actions.put_value(self.find(screen, "search"), text)
        is_panel = self.locators.screen(screen).scope.dialog is None
        if is_panel and not actions.same_text(actions.read_value(self.find(screen, "search")), text):
            actions.set_text(self.find(screen, "search"), text, commit="")

        def state():
            if not self.is_open(screen):
                return ("closed",)
            return ("open", actions.read_value(self.find(screen, "search")), self.read_table(screen, "table").signature())

        final = wait_stable(state, timeout=timeout or self.settings.ui_timeout, what=f"{screen} search", settle=1.0)
        if final == ("closed",):
            return None
        if not actions.same_text(final[1], text):
            raise VerificationFailed(f"put {text!r} into the {screen} search, but it shows {final[1]!r}")
        return self.read_table(screen, "table")

    def read_table_stable(self, screen: str, control: str, title: str | None = None,
                          timeout: float | None = None) -> Grid:
        last: dict[str, Grid] = {}

        def read():
            last["grid"] = self.read_table(screen, control, title)
            return last["grid"].signature()

        wait_stable(read, timeout=timeout or self.settings.ui_timeout, what=f"{screen}.{control}", settle=1.0)
        return last["grid"]

    def click_row(self, row: GridRow, *, double: bool = False) -> None:
        self.bring_to_front()
        click_row(row, double=double)

    def set_date(self, screen: str, control: str, value: Any, title: str | None = None) -> str:
        return actions.set_date(self.find(screen, control, title), value)

    def choose(self, screen: str, control: str, option: str, title: str | None = None) -> str:
        return actions.select_option(self.find(screen, control, title), option)

    def tick(self, screen: str, control: str, checked: bool, title: str | None = None) -> None:
        actions.set_checkbox(self.find(screen, control, title), checked)

    def is_ticked(self, screen: str, control: str, title: str | None = None) -> bool:
        return actions.toggle_state(self.find(screen, control, title))

    def select_tab(self, screen: str, control: str, title: str | None = None) -> None:
        actions.select_tab(self.find(screen, control, title))

    def wait_gone(self, screen: str, control: str, timeout: float | None = None, title: str | None = None) -> None:
        wait_until(lambda: not self.exists(screen, control, title),
                   timeout=timeout or self.settings.ui_timeout, what=f"{screen}.{control} to disappear")

    def press(self, keys: str) -> None:
        actions.ensure_foreground(self.root())
        actions.send_keys(keys)

    def close_editor(self, screen: str, timeout: float | None = None, title: str | None = None) -> None:
        tab = self.activate(screen, title=title)
        item = next((c for c in tab.children() if c.control_type == "TabItem" and c.name == tab.name), None)
        if item is None:
            raise ControlNotFound(f"no tab named {tab.name!r} to close")
        self._close_tab(item, screen, title, timeout or self.settings.ui_timeout)

    def close_all(self, screen: str, timeout: float | None = None, title: str | None = None) -> int:
        closed = 0
        while self.editor_tabs(screen, title):
            self._close_tab(self.editor_tabs(screen, title)[0], screen, title, timeout or self.settings.ui_timeout)
            closed += 1
        return closed

    def _close_tab(self, item: UiaNode, screen: str, title: str | None, timeout: float) -> None:
        tab_title = item.name
        before = len(self.editor_tabs(screen, title))
        self.bring_to_front()
        actions.ensure_foreground(item)
        item.wrapper().click_input()
        self.click("main", "menu_file")
        actions.click(self.wait_for("file_menu", "close"))

        def closed() -> bool:
            return len(self.editor_tabs(screen, title)) < before

        def closed_or_asked():
            if closed():
                return "closed"
            dialogs = actions.open_dialogs(self.root())
            return dialogs[0] if dialogs else None

        outcome = wait_until(closed_or_asked, timeout=timeout, what=f"{tab_title!r} to close")
        if outcome == "closed":
            return
        info = actions.dialog_info(outcome)
        plan = actions.discard_plan(info, actions.editor_title(tab_title))
        if plan is None:
            if "Cancel" in info.buttons:
                actions.press_dialog_button(outcome, "Cancel")
            raise ManualReviewRequired(f"unexpected dialog while closing {tab_title!r}: {info}")
        if plan == "untick":
            try:
                actions.untick_all(outcome)
            except Exception as exc:
                actions.press_dialog_button(outcome, "Cancel")
                raise ManualReviewRequired(f"could not discard {tab_title!r}: {exc}") from None
            actions.press_dialog_button(outcome, "OK")
        else:
            actions.press_dialog_button(outcome, actions.DISCARD_BUTTON)
        wait_until(closed, timeout=timeout, what=f"{tab_title!r} to close")

    def park_mouse(self) -> None:
        from pywinauto import mouse

        r = self.window.rectangle()
        mouse.move(coords=(r.left + (r.right - r.left) // 2, r.top + 8))
        time.sleep(0.2)

    def table_rows(self, screen: str, control: str, title: str | None = None) -> list:
        self.bring_to_front()
        self.park_mouse()
        words, _ = capture_words(self.find(screen, control, title), lang=self.settings.ocr_language)
        return visual_rows(words)

    def _hscroll(self, screen: str, control: str) -> UiaNode | None:
        tab = self.activate(screen)
        grid = self.find(screen, control).rect
        bars = [n for n in preorder(tab) if n.control_type == "ScrollBar" and n.name == "Horizontal" and n.visible
                and not (grid[0] <= n.rect[0] and n.rect[2] <= grid[2] and grid[1] <= n.rect[1] and n.rect[3] <= grid[3])]
        return min(bars, key=lambda b: abs(b.rect[1] - grid[3])) if bars else None

    def _scroll_position(self, bar: UiaNode) -> tuple[float, float]:
        from pywinauto.uia_defines import get_elem_interface

        pattern = get_elem_interface(bar.info.element, "RangeValue")
        return float(pattern.CurrentValue), float(pattern.CurrentMinimum)

    def _press(self, bar: UiaNode | None, button: str) -> bool:
        target = next((c for c in bar.children() if c.control_type == "Button" and c.name == button), None) if bar else None
        if target is None or not target.enabled:
            return False
        actions.ensure_foreground(target)
        target.wrapper().click_input()
        time.sleep(0.4)
        return True

    def _press_scroll(self, screen: str, control: str, button: str) -> bool:
        return self._press(self._hscroll(screen, control), button)

    def _vscroll(self, screen: str, control: str, title: str | None) -> tuple[UiaNode | None, tuple]:
        tab = self.activate(screen, title)
        grid = self.find(screen, control, title).rect
        bars = [n for n in preorder(tab) if n.control_type == "ScrollBar" and n.name == "Vertical" and n.visible
                and n.rect[1] <= grid[1] < n.rect[3]
                and not (grid[0] <= n.rect[0] and n.rect[2] <= grid[2] and grid[1] <= n.rect[1] and n.rect[3] <= grid[3])]
        return (max(bars, key=lambda b: b.rect[1]) if bars else None), grid

    @contextmanager
    def revealed(self, screen: str, control: str, title: str | None = None):
        try:
            for _ in range(8):
                bar, grid = self._vscroll(screen, control, title)
                if bar is None or grid[3] <= bar.rect[3] + 1:
                    break
                if not (self._press(bar, "Page down") or self._press(bar, "Line down")):
                    break
            yield
        finally:
            for _ in range(12):
                bar, _ = self._vscroll(screen, control, title)
                if bar is None or self._scroll_position(bar)[0] <= self._scroll_position(bar)[1]:
                    break
                if not (self._press(bar, "Page up") or self._press(bar, "Line up")):
                    break

    def scroll_home(self, screen: str, control: str) -> None:
        for _ in range(12):
            bar = self._hscroll(screen, control)
            if bar is None:
                return
            value, minimum = self._scroll_position(bar)
            if value <= minimum:
                return
            if not (self._press_scroll(screen, control, "Page left") or self._press_scroll(screen, control, "Column left")):
                return
        raise VerificationFailed(f"could not scroll {screen} back to the start")

    def set_line_cell(self, screen: str, control: str, key: str, column: str, text: str, *,
                      check: Any, left_of_key: bool = False) -> str:
        rows = self.table_rows(screen, control)
        row = line_row(rows, key)
        if row is None:
            raise ControlNotFound(f"no single line with {key!r} in {screen}.{control}")
        y = sum(w.box.center[1] for w in row) / len(row)
        right_edge = self.window.rectangle().right - 8
        target = None
        try:
            for _ in range(4):
                row = row_at(rows, y)
                target = cell_word(rows, row, column, key, left_of_key) if row else None
                if target is not None and target.box.right < right_edge:
                    break
                target = None
                if not self._press_scroll(screen, control, "Page right"):
                    break
                rows = self.table_rows(screen, control)
            if target is None:
                raise ControlNotFound(f"column {column!r} of the line {key!r} is not visible")
            from pywinauto import mouse

            actions.ensure_foreground(self.root())
            mouse.click(coords=(int(target.box.center[0]), int(target.box.center[1])))
            grid = self.find(screen, control)
            editor = wait_until(lambda: next((n for n in preorder(UiaNode(grid.info)) if n.control_type == "Edit"
                                              and actions.has_focus(n)), None),
                                timeout=5, what=f"the editor of {column!r} on line {key!r}")
            shown = actions.set_text(editor, text, check=check, commit="")
            actions.send_keys("{ENTER}")
            time.sleep(0.3)
            grid = self.find(screen, control)
            if any(n.control_type == "Edit" and actions.has_focus(n) for n in preorder(UiaNode(grid.info))):
                actions.send_keys("{ESC}")
                time.sleep(0.3)
            return shown
        finally:
            self.scroll_home(screen, control)

    def read_cell(self, screen: str, control: str, row: GridRow, column: str, title: str | None = None) -> str:
        self.bring_to_front()
        self.park_mouse()
        node = self.find(screen, control, title)
        image = node.wrapper().capture_as_image()
        rows = visual_rows(ocr_words(image, lang=self.settings.ocr_language))
        header = match_headers(rows[0], (column,)).get(column) if rows else None
        if header is None:
            raise ControlNotFound(f"column {column!r} not found in {screen}.{control}")
        left, right = cell_span(image, header)
        top = row.box.top - node.rect[1] - 4
        bottom = row.box.bottom - node.rect[1] + 4
        cell = image.crop((int(left) + 1, max(0, int(top)), int(right) - 1, min(image.height, int(bottom))))
        return read_cell_image(cell, lang=self.settings.ocr_language)
