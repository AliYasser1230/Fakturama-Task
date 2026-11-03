import json
from pathlib import Path

import pytest

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import PaymentMethod
from image_to_cash.flow.matching import CREATE, REVIEW, SELECT, decide_payment
from image_to_cash.flow.payment_method import ensure_payment_method, is_zero, select_payment
from image_to_cash.flow.runner import GateFailed
from image_to_cash.ocr import Box, OcrWord
from image_to_cash.ui.grid_ocr import parse_grid
from tests.fakes import PAYMENT_COLUMNS, FakeApp, grid

BANK = PaymentMethod.BANK_TRANSFER


def _debtor_open(app):
    app.open.add("debtor_editor")
    app.values[("debtor_editor", "payment")] = "Pay Cash"
    return app


def test_existing_method_is_found_and_not_created_again():
    existing = grid(PAYMENT_COLUMNS, ("", "Bank Transfer", "Bank Transfer", "0%", "0", "0"))
    app = FakeApp(tables={("payments_list", "table"): existing})
    checks = ensure_payment_method(app, BANK)
    assert [c.what for c in checks] == ["payment method in terms of payment"]
    assert app.saved == [] and "payment_editor" not in app.open


def test_missing_method_is_created_checked_saved_once_and_rechecked():
    app = FakeApp()
    checks = ensure_payment_method(app, BANK)
    assert all(c.ok for c in checks), [str(c) for c in checks if not c.ok]
    values = {k[1]: v for k, v in app.values.items() if k[0] == "payment_editor"}
    assert values["name"] == values["description"] == "Bank Transfer"
    assert values["payment_code"] == "Credit transfer"
    assert values["account"] == "" and values["standard"] == "Cash"
    assert app.saved == [("payment_editor", "Bank Transfer")]
    assert ("type", "payments_list", "search", "Bank Transfer") in app.calls
    assert any(c.what == "stored payment code" for c in checks)


def test_wrong_field_stops_before_save():
    def wrong_code(app):
        app.values[("payment_editor", "payment_code")] = "Mutually defined "

    app = FakeApp(after={("choose", "payment_editor", "payment_code"): wrong_code})
    with pytest.raises(GateFailed) as exc:
        ensure_payment_method(app, BANK)
    assert [c.what for c in exc.value.result.checks if not c.ok] == ["payment code"]
    assert app.saved == []


def test_conflicting_entry_in_terms_of_payment_needs_review():
    conflict = grid(PAYMENT_COLUMNS, ("", "Bank Transfer", "Wire transfer", "0%", "0", "0"))
    app = FakeApp(tables={("payments_list", "table"): conflict})
    with pytest.raises(ManualReviewRequired, match="conflicts"):
        ensure_payment_method(app, BANK)
    assert app.saved == []


def test_method_offered_on_the_contact_is_selected():
    app = _debtor_open(FakeApp(payment_options=("Pay Cash", "Bank Transfer")))
    check = select_payment(app, BANK)
    assert check.ok and app.values[("debtor_editor", "payment")] == "Bank Transfer"


def test_method_not_offered_on_the_contact_needs_review():
    app = _debtor_open(FakeApp())
    with pytest.raises(ManualReviewRequired, match="offers 0 entries"):
        select_payment(app, BANK)


@pytest.mark.parametrize("rows, action", [
    ([("", "Bank Transfer", "Bank Transfer", "0%", "0", "0")], SELECT),
    ([("", "Bank Transfer", "Bank Transfer", "0%", "0", "0")] * 2, REVIEW),
    ([("", "Bank Transfer", "Wire", "0%", "0", "0")], REVIEW),
    ([("", "Transfer", "Bank Transfer", "0%", "0", "0")], REVIEW),
    ([("", "Cash", "Pay Cash", "0%", "0", "0")], CREATE),
    ([], CREATE),
])
def test_decide_payment(rows, action):
    assert decide_payment(grid(PAYMENT_COLUMNS, *rows), "Bank Transfer").action == action


def test_real_terms_of_payment_capture():
    data = json.loads((Path(__file__).parent / "fixtures" / "ocr" / "payments_list_table.json").read_text())
    words = [OcrWord(w["text"], Box(*w["box"])) for w in data["words"]]
    parsed = parse_grid(words, PAYMENT_COLUMNS, required=("Name", "Description"))
    assert [(r.cells["Name"], r.cells["Description"]) for r in parsed.rows] == [("Cash", "Pay Cash")]
    assert decide_payment(parsed, "Bank Transfer").action == CREATE


@pytest.mark.parametrize("shown, zero", [("0", True), ("0%", True), ("0.00 %", True), ("1", False), ("", False)])
def test_is_zero(shown, zero):
    assert is_zero(shown) is zero
