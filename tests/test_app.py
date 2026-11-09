import json
from pathlib import Path

import pytest

from image_to_cash.settings import Settings
from image_to_cash.ui.app import pick_fakturama_window
from image_to_cash.ui.finder import DictNode, UiaNode
from image_to_cash.ui.locators import load_locators

FIXTURES = Path(__file__).parent / "fixtures" / "uia"


def _recording(stem):
    return DictNode(json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def locators():
    return load_locators(Settings().locators_file)


class FakeRect:
    left, top, right, bottom = 1, 2, 3, 4


class FakeInfo:
    def __init__(self, name="Cust.Ref.", children=()):
        self.name = name
        self.control_type = "Edit"
        self.visible = True
        self.enabled = True
        self.rectangle = FakeRect()
        self._children = list(children)
        self.children_calls = 0

    def children(self):
        self.children_calls += 1
        return self._children


class BrokenInfo(FakeInfo):
    @property
    def name(self):
        raise RuntimeError("COM element is gone")

    @name.setter
    def name(self, value):
        pass


def test_uia_node_reads_each_property_once():
    child = FakeInfo("child")
    info = FakeInfo(children=[child])
    node = UiaNode(info)
    assert node.name == "Cust.Ref." and node.rect == (1, 2, 3, 4) and node.visible
    assert [c.name for c in node.children()] == ["child"]
    node.children()
    assert info.children_calls == 1


def test_uia_node_uses_safe_defaults_when_the_element_is_gone():
    node = UiaNode(BrokenInfo())
    assert node.name == ""
    assert node.value is None


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
