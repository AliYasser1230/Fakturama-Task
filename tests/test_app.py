import json
import sys
from pathlib import Path

import pytest

import main
from image_to_cash.settings import Settings
from image_to_cash.ui.app import format_probe, probe_tree
from image_to_cash.ui.finder import DictNode, UiaNode
from image_to_cash.ui.locators import load_locators

FIXTURES = Path(__file__).parent / "fixtures" / "uia"


def _recording(stem):
    return DictNode(json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def locators():
    return load_locators(Settings().locators_file)


def test_probe_reports_only_the_open_screens(locators):
    results = probe_tree(_recording("02_order_editor"), locators)
    screens = {r.screen for r in results}
    assert {"main", "order_editor"} <= screens
    assert "select_address" not in screens and "invoice_editor" not in screens
    order = [r for r in results if r.screen == "order_editor"]
    assert {r.control for r in order if not r.found} == {"tab_delivery_address", "delivery_address"}
    number = next(r for r in order if r.control == "number")
    assert "value='PO000001'" in number.detail


def test_probe_lists_controls_that_are_not_visible_now(locators):
    results = probe_tree(_recording("05_debtor_main_address"), locators, ["debtor_editor"])
    missing = {r.control for r in results if not r.found}
    assert {"alias", "payment"} <= missing
    assert {"street", "zip", "city"}.isdisjoint(missing)


def test_format_probe(locators):
    lines = format_probe(probe_tree(_recording("12_invoice_editor"), locators, ["invoice_editor"]))
    assert lines[0] == "invoice_editor: 17/21 found"
    assert any(line.strip().startswith("ok  paid") for line in lines)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows message")
def test_cli_probe_needs_windows(capsys):
    assert main.main(["probe"]) == 2
    assert "Windows" in capsys.readouterr().err


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


def test_a_closed_menu_is_not_reported(locators):
    assert "data_menu" not in {r.screen for r in probe_tree(_recording("00_main"), locators)}
    open_menu = probe_tree(_recording("01_data_menu"), locators, ["data_menu"])
    assert len(open_menu) == 5 and all(r.found for r in open_menu)
