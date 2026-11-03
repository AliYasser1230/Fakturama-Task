from datetime import date

import pytest

from image_to_cash.errors import VerificationFailed
from image_to_cash.ui.actions import (
    DialogInfo,
    date_keys,
    dialog_info,
    discard_choice,
    discard_plan,
    editor_title,
    escape_keys,
    exactly,
    is_dirty,
    parse_display_date,
    same_text,
)
from image_to_cash.ui.finder import DictNode


def test_escape_keys_protects_send_keys_syntax():
    assert escape_keys("WEB-2026-0714-A17") == "WEB-2026-0714-A17"
    assert escape_keys("10% (net)") == "10{%} {(}net{)}"
    assert escape_keys("a+b^c~d{e}[f]") == "a{+}b{^}c{~}d{{}e{}}{[}f{]}"


def test_same_text_ignores_only_surrounding_and_repeated_spaces():
    assert same_text("Credit transfer ", "Credit transfer")
    assert same_text("Northstar  Office GmbH", "Northstar Office GmbH")
    assert not same_text("credit transfer", "Credit transfer")
    assert exactly("Net")("Net ") and not exactly("Net")("Gross")


def test_unsaved_marker():
    assert is_dirty("*New TAX Rate") and editor_title("*New TAX Rate") == "New TAX Rate"
    assert not is_dirty("New Order") and editor_title("New Order") == "New Order"


ECLIPSE_SAVE = DialogInfo("Save Resource", ("'New Order' has been modified. Save changes?",), ("Cancel", "No", "Yes"))


@pytest.mark.parametrize("dialog, editor, expected", [
    (ECLIPSE_SAVE, "New Order", "No"),
    (ECLIPSE_SAVE, "New Debtor", None),
    (DialogInfo("Save Parts", ("Select the parts to save:",), ("Cancel", "OK")), "New TAX Rate", None),
    (DialogInfo("Confirm deleting", ("Entry null will be deleted!",), ("Cancel", "OK")), "New Order", None),
    (DialogInfo("Save Resource", ("'New Order' has been modified. Save changes?",), ("No", "Yes")), "New Order", None),
    (DialogInfo("Question", ("'New Order': delete all items?",), ("Cancel", "No", "Yes")), "New Order", None),
])
def test_discard_only_answers_a_recognised_save_question(dialog, editor, expected):
    assert discard_choice(dialog, editor) == expected


def test_dialog_info_reads_texts_and_buttons():
    window = DictNode({"control_type": "Window", "name": "Save Parts", "children": [
        {"control_type": "Text", "name": "Select the parts to save:"},
        {"control_type": "List", "children": [{"control_type": "ListItem", "name": "New TAX Rate"}]},
        {"control_type": "Pane", "children": [
            {"control_type": "Button", "name": "OK"}, {"control_type": "Button", "name": "Cancel"}]},
        {"control_type": "TitleBar", "children": [{"control_type": "Button", "name": "Close"}]},
    ]})
    info = dialog_info(window)
    assert info.title == "Save Parts"
    assert info.texts == ("Select the parts to save:",)
    assert info.buttons == ("Cancel", "OK")
    assert info.items == ("New TAX Rate",)
    assert discard_choice(info, "New TAX Rate") is None


SAVE_PARTS = DialogInfo("Save Parts", ("New Order", "Select the parts to save:"), ("Cancel", "OK"), ("New Order",))


@pytest.mark.parametrize("dialog, editor, expected", [
    (SAVE_PARTS, "New Order", "untick"),
    (SAVE_PARTS, "New Debtor", None),
    (DialogInfo("Save Parts", (), ("Cancel", "OK"), ("New Order", "New TAX Rate")), "New Order", None),
    (DialogInfo("Save Parts", (), ("OK",), ("New Order",)), "New Order", None),
    (ECLIPSE_SAVE, "New Order", "no"),
    (DialogInfo("Confirm deleting", ("Entry null will be deleted!",), ("Cancel", "OK")), "New Order", None),
])
def test_discard_plan(dialog, editor, expected):
    assert discard_plan(dialog, editor) == expected


@pytest.mark.parametrize("shown, expected", [
    ("Jul 14, 2026", date(2026, 7, 14)),
    ("Nov 3, 2026", date(2026, 11, 3)),
    ("14.07.2026", date(2026, 7, 14)),
    ("Jul 14, 14", None),
    ("Feb 30, 2026", None),
    ("<choose date>", None),
])
def test_parse_display_date(shown, expected):
    assert parse_display_date(shown) == expected


def test_date_keys_follow_the_fields_order():
    assert date_keys("Nov 3, 2026", date(2026, 7, 14)) == "{HOME}07142026{TAB}"
    assert date_keys("03.11.2026", date(2026, 7, 14)) == "{HOME}14072026{TAB}"
    with pytest.raises(VerificationFailed, match="format"):
        date_keys("2026-11-03", date(2026, 7, 14))
