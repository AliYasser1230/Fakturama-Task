from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from image_to_cash.errors import ControlNotFound, FlowStopped, ManualReviewRequired
from image_to_cash.settings import Settings
from image_to_cash.ui.finder import Node, UiaNode, locate, resolve, scope_root
from image_to_cash.ui.locators import Locators, Scope, load_locators
from image_to_cash.ui.waits import wait_until


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

    def close_editor(self, screen: str, timeout: float | None = None, title: str | None = None) -> None:
        from image_to_cash.ui import actions

        timeout = timeout or self.settings.ui_timeout
        tab = self.wait_open(screen, title=title)
        tab_title = tab.name
        item = next((c for c in tab.children() if c.control_type == "TabItem" and c.name == tab_title), None)
        if item is None:
            raise ControlNotFound(f"no tab named {tab_title!r} to close")
        actions.select_tab(item)
        self.bring_to_front()
        actions.ensure_foreground(self.root())
        actions.send_keys("^w")

        def closed_or_asked():
            if not self.is_open(screen, title):
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
        self.wait_closed(screen, timeout, title)
