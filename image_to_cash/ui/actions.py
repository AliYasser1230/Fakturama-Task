from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from image_to_cash.errors import ControlNotFound, ManualReviewRequired, VerificationFailed
from image_to_cash.ui.finder import UiaNode, preorder
from image_to_cash.ui.waits import wait_until

SEND_KEYS_SPECIAL = set("{}+^%~()[]")
STATE_DIRTY = "*"
DISCARD_BUTTON = "No"
SAVE_QUESTION = re.compile(r"(?i)save|modified|changes")
SAVE_PARTS = "Save Parts"
LVM_GETITEMSTATE = 0x1000 + 44
LVIS_STATEIMAGEMASK = 0xF000
CHECKED_STATE_IMAGE = 2
MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
US_DATE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
DOTTED_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def escape_keys(text: str) -> str:
    return "".join(f"{{{c}}}" if c in SEND_KEYS_SPECIAL else c for c in text)


def same_text(a: str | None, b: str | None) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def exactly(expected: str) -> Callable[[str], bool]:
    return lambda shown: same_text(shown, expected)


def editor_title(tab_name: str) -> str:
    return tab_name[1:] if tab_name.startswith(STATE_DIRTY) else tab_name


def is_dirty(tab_name: str) -> bool:
    return tab_name.startswith(STATE_DIRTY)


def parse_display_date(text: str | None) -> date | None:
    shown = " ".join((text or "").split())
    try:
        m = US_DATE.match(shown)
        if m and m.group(1) in MONTH_ABBR:
            return date(int(m.group(3)), MONTH_ABBR.index(m.group(1)) + 1, int(m.group(2)))
        m = DOTTED_DATE.match(shown)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def date_keys(current: str, value: date) -> str:
    shown = " ".join((current or "").split())
    if US_DATE.match(shown):
        digits = f"{value.month:02d}{value.day:02d}{value.year:04d}"
    elif DOTTED_DATE.match(shown):
        digits = f"{value.day:02d}{value.month:02d}{value.year:04d}"
    else:
        raise VerificationFailed(f"date field shows {current!r}, a format this tool does not know")
    return "{HOME}" + digits + "{TAB}"


@dataclass(frozen=True)
class DialogInfo:
    title: str
    texts: tuple[str, ...]
    buttons: tuple[str, ...]
    items: tuple[str, ...] = ()


def discard_choice(dialog: DialogInfo, editor: str) -> str | None:
    wording = " ".join((dialog.title,) + dialog.texts)
    if set(dialog.buttons) != {"Yes", DISCARD_BUTTON, "Cancel"}:
        return None
    if not SAVE_QUESTION.search(wording) or not editor or editor not in wording:
        return None
    return DISCARD_BUTTON


def discard_plan(dialog: DialogInfo, editor: str) -> str | None:
    if dialog.title == SAVE_PARTS and set(dialog.buttons) == {"OK", "Cancel"} and dialog.items == (editor,):
        return "untick"
    return "no" if discard_choice(dialog, editor) else None


def _pattern(node: UiaNode, name: str) -> Any:
    from pywinauto.uia_defines import get_elem_interface

    return get_elem_interface(node.info.element, name)


def has_pattern(node: UiaNode, name: str) -> bool:
    try:
        _pattern(node, name)
        return True
    except Exception:
        return False


def fresh(node: UiaNode) -> UiaNode:
    return UiaNode(node.info)


def read_value(node: UiaNode) -> str:
    try:
        return _pattern(node, "Value").CurrentValue or ""
    except Exception:
        raise VerificationFailed(f"{node} has no readable value") from None


def foreground_pid() -> int:
    import ctypes
    from ctypes import wintypes

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def ensure_foreground(node: UiaNode) -> None:
    owner = node.info.process_id
    if foreground_pid() != owner:
        node.wrapper().set_focus()
        time.sleep(0.2)
    if foreground_pid() != owner:
        raise VerificationFailed("Fakturama is not the window in front; not typing into another program")


def send_keys(keys: str) -> None:
    from pywinauto.keyboard import send_keys as _send

    _send(keys, with_spaces=True, with_tabs=False, with_newlines=False, pause=0.01)


def click(node: UiaNode) -> None:
    if node.control_type in {"Button", "MenuItem", "SplitButton", "Hyperlink"} and has_pattern(node, "Invoke"):
        _pattern(node, "Invoke").Invoke()
    elif node.control_type == "TabItem":
        select_tab(node)
    else:
        ensure_foreground(node)
        node.wrapper().click_input()


def set_text(
    node: UiaNode,
    text: str,
    *,
    check: Callable[[str], bool] | None = None,
    commit: str = "{TAB}",
    timeout: float = 5.0,
) -> str:
    if not node.enabled:
        raise VerificationFailed(f"{node} is disabled")
    check = check or exactly(text)
    node.wrapper().set_focus()
    ensure_foreground(node)
    send_keys("^a" + (escape_keys(text) if text else "{DEL}") + commit)
    shown: list[str] = [""]

    def done() -> bool:
        shown[0] = read_value(node)
        return check(shown[0])

    try:
        wait_until(done, timeout=timeout, what=f"{node} to show {text!r}")
    except Exception:
        raise VerificationFailed(f"typed {text!r} into {node}, but it shows {shown[0]!r}") from None
    return shown[0]


def list_items(combo: UiaNode) -> list[UiaNode]:
    items = []
    for child in fresh(combo).children():
        if child.control_type == "List":
            items += [c for c in child.children() if c.control_type == "ListItem"]
    return items


def select_option(combo: UiaNode, option: str, *, timeout: float = 5.0) -> str:
    if same_text(read_value(combo), option):
        return read_value(combo)
    opener = [c for c in fresh(combo).children() if c.control_type == "Button" and c.name == "Open"]
    if not opener:
        raise ControlNotFound(f"{combo} has no dropdown button")
    ensure_foreground(combo)
    opener[0].wrapper().click_input()
    items = wait_until(lambda: list_items(combo), timeout=timeout, what=f"the options of {combo}")
    matches = [i for i in items if same_text(i.name, option)]
    if len(matches) != 1:
        send_keys("{ESC}")
        names = [i.name.strip() for i in items]
        raise ManualReviewRequired(f"{len(matches)} options named {option!r} in {combo}; options: {names}")
    item = matches[0]
    if has_pattern(item, "ScrollItem"):
        _pattern(item, "ScrollItem").ScrollIntoView()
    fresh_item = next(i for i in list_items(combo) if same_text(i.name, option))
    fresh_item.wrapper().click_input()
    try:
        wait_until(lambda: same_text(read_value(combo), option), timeout=timeout, what=f"{combo} to show {option!r}")
    except Exception:
        raise VerificationFailed(f"chose {option!r} in {combo}, but it shows {read_value(combo)!r}") from None
    return read_value(combo)


def set_date(node: UiaNode, value: date, *, timeout: float = 5.0) -> str:
    if not node.enabled:
        raise VerificationFailed(f"{node} is disabled")
    keys = date_keys(read_value(node), value)
    node.wrapper().set_focus()
    ensure_foreground(node)
    send_keys(keys)
    try:
        wait_until(lambda: parse_display_date(read_value(node)) == value, timeout=timeout, what=f"{node} to show {value}")
    except Exception:
        raise VerificationFailed(f"set {node} to {value}, but it shows {read_value(node)!r}") from None
    return read_value(node)


def toggle_state(node: UiaNode) -> bool:
    return int(_pattern(node, "Toggle").CurrentToggleState) == 1


def set_checkbox(node: UiaNode, checked: bool, *, timeout: float = 5.0) -> None:
    if toggle_state(node) != checked:
        _pattern(node, "Toggle").Toggle()
    try:
        wait_until(lambda: toggle_state(node) == checked, timeout=timeout, what=f"{node} to be {'on' if checked else 'off'}")
    except Exception:
        raise VerificationFailed(f"{node} did not become {'ticked' if checked else 'unticked'}") from None


def is_selected(node: UiaNode) -> bool:
    try:
        return bool(_pattern(node, "SelectionItem").CurrentIsSelected)
    except Exception:
        return False


def select_tab(node: UiaNode, *, timeout: float = 5.0) -> None:
    if is_selected(node):
        return
    try:
        _pattern(node, "SelectionItem").Select()
    except Exception:
        ensure_foreground(node)
        node.wrapper().click_input()
    try:
        wait_until(lambda: is_selected(node), timeout=timeout, what=f"{node} to be selected")
    except Exception:
        raise VerificationFailed(f"tab {node.name!r} did not become selected") from None


def dialog_info(window: UiaNode) -> DialogInfo:
    texts, buttons, items = [], [], []
    for n in list(preorder(window))[1:]:
        if n.control_type == "Text" and n.name:
            texts.append(n.name)
        elif n.control_type == "ListItem" and n.name:
            items.append(n.name)
        elif n.control_type == "Button" and n.name and n.name not in {"Close", "Minimize", "Maximize"}:
            buttons.append(n.name)
    return DialogInfo(window.name, tuple(texts), tuple(sorted(buttons)), tuple(items))


def open_dialogs(main: UiaNode) -> list[UiaNode]:
    return [c for c in main.children() if c.control_type == "Window" and c.visible]


def press_dialog_button(window: UiaNode, name: str) -> None:
    stack = list(window.children())
    while stack:
        n = stack.pop()
        if n.control_type == "Button" and n.name == name:
            click(n)
            return
        stack.extend(n.children())
    raise ControlNotFound(f"no button {name!r} in dialog {window.name!r}")



def is_row_checked(listview: Any, index: int) -> bool:
    state = listview.send_message(LVM_GETITEMSTATE, index, LVIS_STATEIMAGEMASK)
    return (state & LVIS_STATEIMAGEMASK) >> 12 == CHECKED_STATE_IMAGE


def untick_all(dialog: UiaNode, *, timeout: float = 5.0) -> None:
    from pywinauto.controls.common_controls import ListViewWrapper

    lists = [n for n in preorder(dialog) if n.control_type == "List"]
    if len(lists) != 1:
        raise ControlNotFound(f"expected one list in dialog {dialog.name!r}, found {len(lists)}")
    listview = ListViewWrapper(lists[0].info.handle)
    rows = [n for n in preorder(lists[0]) if n.control_type == "ListItem"]
    if len(rows) != listview.item_count():
        raise VerificationFailed(f"dialog {dialog.name!r}: {len(rows)} rows seen, list control has {listview.item_count()}")
    for index, row in enumerate(rows):
        if not is_row_checked(listview, index):
            continue
        label = next((n for n in preorder(row) if n.control_type == "Text"), row)
        ensure_foreground(label)
        label.wrapper().click_input()
        time.sleep(0.2)
        if is_row_checked(listview, index):
            send_keys(" ")
        try:
            wait_until(lambda: not is_row_checked(listview, index), timeout=timeout, what=f"{row.name!r} to be unticked")
        except Exception:
            raise VerificationFailed(f"could not untick {row.name!r} in {dialog.name!r}") from None
    if any(is_row_checked(listview, i) for i in range(listview.item_count())):
        raise VerificationFailed(f"something is still ticked in {dialog.name!r}")
