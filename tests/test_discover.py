import sys

import pytest

import main
from image_to_cash.ui.discover import SCREENS, format_node, format_tree, pick_fakturama_window, safe_name


def test_screens_are_unique_and_described():
    keys = [s.key for s in SCREENS]
    assert len(keys) == len(set(keys))
    assert all(s.instructions.strip() for s in SCREENS)
    menu = next(s for s in SCREENS if s.key == "data_menu")
    assert menu.countdown > 0 and menu.focus is False


def test_format_node_shows_locator_properties():
    line = format_node({
        "control_type": "Edit", "name": "", "automation_id": "", "class_name": "Edit",
        "rect": [10, 20, 110, 40], "enabled": True, "visible": True,
        "patterns": ["Value", "LegacyIAccessible"], "value": "WEB-2026", "labeled_by": "Cust.Ref.",
    })
    assert line.startswith("Edit  name=''")
    assert "class='Edit'" in line and "rect=(10,20,110,40)" in line
    assert "patterns=Value,LegacyIAccessible" in line
    assert "value='WEB-2026'" in line and "labeled_by='Cust.Ref.'" in line
    assert "NOT" not in line


def test_format_node_flags_disabled_and_hidden():
    line = format_node({"control_type": "Button", "name": "Save", "enabled": False, "visible": False})
    assert "NOT enabled/visible" in line


def test_format_tree_indents_children():
    tree = {"control_type": "Window", "name": "Fakturama",
            "children": [{"control_type": "ToolBar", "name": "",
                          "children": [{"control_type": "Button", "name": "Order"}]}]}
    lines = format_tree(tree)
    assert lines[0].startswith("Window") and lines[1].startswith("  ToolBar") and lines[2].startswith("    Button")


def test_safe_name():
    assert safe_name("Select the address") == "Select_the_address"
    assert safe_name("") == "untitled"
    assert safe_name("a/b\\c:d*?") == "a_b_c_d"


def test_pick_fakturama_window_only_takes_fakturamas_own_windows():
    console, browser, splash, main_window = object(), object(), object(), object()
    windows = [
        ("C:\\Fakturama-Task - PowerShell", "CASCADIA_HOSTING_WINDOW_CLASS", console),
        ("Downloads - Fakturama - Microsoft Edge", "Chrome_WidgetWin_1", browser),
        ("Fakturama", "SWT_Window0", splash),
        ("Fakturama - C:\\FakturamaData", "SWT_Window0", main_window),
    ]
    assert pick_fakturama_window(windows) is main_window
    assert pick_fakturama_window(windows[:3]) is splash
    assert pick_fakturama_window(windows[:2]) is None


def test_cli_discover_list(capsys):
    assert main.main(["discover", "--list"]) == 0
    out = capsys.readouterr().out
    assert "order_editor" in out and "select_address" in out


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows message")
def test_cli_discover_needs_windows(capsys):
    assert main.main(["discover"]) == 2
    assert "Windows" in capsys.readouterr().err
