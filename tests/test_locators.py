import json
from pathlib import Path

import pytest

from image_to_cash.errors import ControlNotFound
from image_to_cash.settings import Settings
from image_to_cash.ui.finder import DictNode, locate, resolve, scope_root
from image_to_cash.ui.locators import Locator, Scope, load_locators

FIXTURES = Path(__file__).parent / "fixtures" / "uia"


def _recording(stem: str) -> DictNode:
    return DictNode(json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def locators():
    return load_locators(Settings().locators_file)


@pytest.fixture(scope="module")
def recordings():
    return {p.stem: _recording(p.stem) for p in sorted(FIXTURES.glob("*.json"))}


def test_every_control_resolves_in_a_real_recording(locators, recordings):
    missing = []
    for screen_name, screen in locators.screens.items():
        for control_name, loc in screen.controls.items():
            found = False
            for root in recordings.values():
                try:
                    resolve(scope_root(root, screen.scope), loc)
                    found = True
                    break
                except ControlNotFound:
                    continue
            if not found:
                missing.append(f"{screen_name}.{control_name}")
    assert missing == []


@pytest.mark.parametrize("recording, screen, control, expected", [
    ("02_order_editor", "order_editor", "number", {"value": "PO000001"}),
    ("02_order_editor", "order_editor", "cust_ref", {"rect": (270, 218, 582, 239)}),
    ("02_order_editor", "order_editor", "shipping_amount", {"value": "$0.00", "rect": (845, 739, 993, 762)}),
    ("02_order_editor", "order_editor", "select_address", {"rect": (245, 267, 265, 287)}),
    ("02_order_editor", "order_editor", "new_address", {"rect": (245, 295, 265, 315)}),
    ("02_order_editor", "order_editor", "items", {"rect": (243, 334, 1091, 660)}),
    ("04_select_product", "select_product", "table", {"rect": (150, 180, 902, 600)}),
    ("05_debtor_main_address", "debtor_editor", "first_name", {"rect": (338, 275, 550, 296)}),
    ("05_debtor_main_address", "debtor_editor", "last_name", {"rect": (556, 275, 768, 296)}),
    ("05_debtor_main_address", "debtor_editor", "zip", {"rect": (347, 638, 409, 659)}),
    ("05_debtor_main_address", "debtor_editor", "city", {"rect": (415, 638, 628, 659)}),
    ("06_debtor_misc", "debtor_editor", "payment", {"value": "Pay Cash"}),
    ("13_payment_code_open", "payment_editor", "payment_code", {"value": "Mutually defined "}),
    ("10_product_editor", "product_editor", "price_gross", {"rect": (341, 392, 473, 413)}),
    ("12_invoice_editor", "invoice_editor", "number", {"value": "INV000001"}),
    ("12_invoice_editor", "invoice_editor", "payment", {"value": "Pay Cash"}),
    ("12_invoice_editor", "invoice_editor", "pay_until", {"rect": (552, 778, 631, 795)}),
])
def test_controls_resolve_to_the_right_element(locators, recording, screen, control, expected):
    node = locate(_recording(recording), locators, screen, control)
    if "value" in expected:
        assert node.value == expected["value"]
    if "rect" in expected:
        assert node.rect == expected["rect"]


def test_dialog_scope_is_missing_when_the_dialog_is_closed(locators):
    with pytest.raises(ControlNotFound, match="select_address.ok|dialog 'Select the address'"):
        locate(_recording("02_order_editor"), locators, "select_address", "ok")


def test_unknown_screen_or_control_names_the_alternatives(locators):
    with pytest.raises(KeyError, match="order_editor"):
        locators.screen("order_editr")
    with pytest.raises(KeyError, match="cust_ref"):
        locators.control("order_editor", "custref")


def _tree(*children, name="root", control_type="Window"):
    return {"control_type": control_type, "name": name, "children": list(children)}


def _n(control_type, name="", **extra):
    return {"control_type": control_type, "name": name, **extra}


def test_after_takes_controls_until_the_next_label():
    root = DictNode(_tree(
        _n("Text", "ZIP - City"),
        {"control_type": "Pane", "children": [_n("Edit", value="10117"), _n("Edit", value="Berlin")]},
        _n("Text", "Telefax"),
        _n("Edit", value="fax"),
    ))
    assert resolve(root, Locator(type="Edit", after={"name": "ZIP - City"})).value == "10117"
    assert resolve(root, Locator(type="Edit", after={"name": "ZIP - City"}, index=2)).value == "Berlin"
    with pytest.raises(ControlNotFound, match="wanted number 3"):
        resolve(root, Locator(type="Edit", after={"name": "ZIP - City"}, index=3))


def test_hidden_label_does_not_end_an_after_search():
    root = DictNode(_tree(
        _n("Text", "Shipping"),
        {"control_type": "ComboBox", "name": "Shipping", "children": [_n("Text", "Shipping", visible=False)]},
        _n("Edit", value="$0.00"),
    ))
    assert resolve(root, Locator(type="Edit", after={"name": "Shipping"})).value == "$0.00"


def test_ambiguous_name_is_an_error_not_a_guess():
    root = DictNode(_tree(_n("Button", "OK"), _n("Button", "OK")))
    with pytest.raises(ControlNotFound, match="2 matches"):
        resolve(root, Locator(type="Button", name="OK"))
    assert resolve(root, Locator(type="Button", name="OK", index=2)) is root.children()[1]


def test_hidden_controls_never_match():
    root = DictNode(_tree(_n("Edit", "Name", visible=False), _n("Edit", "Name")))
    assert resolve(root, Locator(type="Edit", name="Name")) is root.children()[1]


def test_within_limits_the_search_to_one_container():
    root = DictNode(_tree(
        {"control_type": "Group", "name": "Create a follow-up document", "children": [_n("Button", "Invoice")]},
        _n("Button", "Invoice"),
    ))
    loc = Locator(type="Button", name="Invoice", within={"type": "Group", "name": "Create a follow-up document"})
    assert resolve(root, loc) is root.children()[0].children()[0]


def test_grid_is_an_empty_pane_with_only_scrollbars():
    table = {"control_type": "Pane", "rect": [0, 100, 500, 400], "children": [_n("ScrollBar", "Vertical")]}
    small = {"control_type": "Pane", "rect": [0, 0, 500, 20]}
    filled = {"control_type": "Pane", "rect": [0, 0, 500, 400], "children": [_n("Edit")]}
    root = DictNode(_tree(small, filled, table))
    assert resolve(root, Locator(type="Grid")).rect == (0, 100, 500, 400)


def test_name_re_matches_the_whole_name():
    root = DictNode(_tree(_n("ComboBox", "!editorPaymentPaymentcode!"), _n("ComboBox", "Payment")))
    loc = Locator(type="ComboBox", name_re="(?i)!?editorPaymentPaymentcode!?|payment ?code")
    assert resolve(root, loc).name == "!editorPaymentPaymentcode!"


def test_tab_scope_allows_the_unsaved_marker(locators):
    root = DictNode(_tree({"control_type": "Tab", "name": "*New Order", "children": [_n("Edit", "Cust.Ref.")]}))
    assert locate(root, locators, "order_editor", "cust_ref").name == "Cust.Ref."


@pytest.mark.parametrize("spec, message", [
    ({"type": "Edit", "name": "A", "name_re": "A"}, "either name or name_re"),
    ({"type": "Edit", "columns": ["A"]}, "only allowed for type Grid"),
    ({"type": "Edit", "nmae": "A"}, "Extra inputs"),
    ({"type": "Edit", "index": 0}, "greater than or equal to 1"),
    ({"type": "Edit", "name_re": "("}, "not a valid regular expression"),
])
def test_invalid_locators_are_rejected(spec, message):
    with pytest.raises(ValueError, match=message):
        Locator.model_validate(spec)


def test_scope_needs_exactly_one_kind():
    with pytest.raises(ValueError, match="exactly one"):
        Scope.model_validate({"window": "main", "dialog": "X"})
    with pytest.raises(ValueError, match="exactly one"):
        Scope.model_validate({})


def test_bad_yaml_names_the_screen(tmp_path):
    bad = tmp_path / "locators.yaml"
    bad.write_text("order_editor:\n  scope: {tab: X}\n  controls:\n    a: {type: Edit, typo: 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="screen 'order_editor' is invalid"):
        load_locators(bad)
