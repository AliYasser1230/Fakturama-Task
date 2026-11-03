import pytest

from image_to_cash.errors import ManualReviewRequired, NotBuiltYet
from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.debtor import select_debtor
from image_to_cash.flow.order import open_order
from image_to_cash.flow.products import add_products
from image_to_cash.flow.runner import GateFailed, RunContext
from image_to_cash.settings import Settings
from tests.fakes import ADDRESS_COLUMNS, ITEM_COLUMNS, PRODUCT_COLUMNS, FakeApp, grid

CONTACT_ROW = ("CUST000001", "Marta", "Klein", "Northstar Office GmbH", "10117", "Berlin")
INVOICE_TEXT = "Northstar Office GmbH\nMarta Klein\nFriedrichstrasse 88\nDE-10117 Berlin\nGermany"
DELIVERY_TEXT = "Northstar Office Warehouse\nBeusselstrasse 44\nDE-10553 Berlin\nGermany"


@pytest.fixture
def order(sample_expected_path):
    return OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))


def _ready(app, order):
    ctx = RunContext(order=order, app=app, settings=Settings())
    open_order(ctx)
    return ctx


def _address_app(rows, invoice=INVOICE_TEXT, delivery=DELIVERY_TEXT):
    on_ok = {("order_editor", "address"): invoice}
    present = {("order_editor", "tab_invoice_address")}
    if delivery is not None:
        on_ok[("order_editor", "delivery_address")] = delivery
        present.add(("order_editor", "tab_delivery_address"))
    return FakeApp(tables={("select_address", "table"): grid(ADDRESS_COLUMNS, *rows)},
                   on_ok={"select_address": on_ok}, present=present)


def test_existing_contact_is_selected_and_both_addresses_are_checked(order):
    app = _address_app([CONTACT_ROW])
    result = select_debtor(_ready(app, order))
    assert result.ok
    assert ("type", "select_address", "search", "Northstar Office GmbH") in app.calls
    assert ("click_row", dict(zip(ADDRESS_COLUMNS, CONTACT_ROW)), False) in app.calls
    assert ("click", "select_address", "ok") in app.calls
    whats = [c.what for c in result.checks]
    assert "Invoice address street" in whats and "Delivery address street" in whats


def test_wrong_filled_in_address_fails_the_check(order):
    app = _address_app([CONTACT_ROW], invoice=INVOICE_TEXT.replace("Friedrichstrasse 88", "Hauptstrasse 1"))
    with pytest.raises(GateFailed) as exc:
        select_debtor(_ready(app, order))
    assert [c.what for c in exc.value.result.checks if not c.ok] == ["Invoice address street"]


def test_missing_delivery_address_fails_when_it_differs_from_billing(order):
    app = _address_app([CONTACT_ROW], delivery=None)
    with pytest.raises(GateFailed) as exc:
        select_debtor(_ready(app, order))
    assert [c.what for c in exc.value.result.checks if not c.ok] == ["Delivery address"]


def test_conflicting_contact_cancels_and_asks_for_review(order):
    app = _address_app([("CUST000001", "Marta", "Klein", "Northstar Office GmbH", "99999", "Hamburg")])
    with pytest.raises(ManualReviewRequired, match="same Company differ"):
        select_debtor(_ready(app, order))
    assert ("click", "select_address", "cancel") in app.calls
    assert "select_address" not in app.open


def test_unknown_contact_cancels_and_hands_over_to_creation(order):
    app = _address_app([])
    with pytest.raises(NotBuiltYet, match="2.5-2.13"):
        select_debtor(_ready(app, order))
    assert app.calls[-1] == ("click", "select_address", "cancel")


def _product_app(rows, lines=None):
    tables = {("select_product", "table"): grid(PRODUCT_COLUMNS, *rows)}
    on_ok = {"select_product": {("order_editor", "items"): grid(ITEM_COLUMNS, *(lines or []))}}
    return FakeApp(tables=tables, on_ok=on_ok)


def test_existing_product_is_selected_and_its_line_checked(order):
    line = ("1", "1", "CHR-ERG-01", "", "Ergonomic Desk Chair", "Ergonomic Desk Chair", "VAT 19%", "$250.00")
    app = _product_app([("CHR-ERG-01", "Ergonomic Desk Chair", "", "0", "$297.50", "VAT 19%")], [line])
    with pytest.raises(NotBuiltYet, match="3.13-3.16"):
        add_products(_ready(app, order))
    assert ("type", "select_product", "search", "CHR-ERG-01") in app.calls
    assert ("click", "select_product", "ok") in app.calls


def test_selected_product_without_a_new_line_needs_review(order):
    app = _product_app([("CHR-ERG-01", "Ergonomic Desk Chair", "", "0", "$297.50", "VAT 19%")], [])
    with pytest.raises(ManualReviewRequired, match="order line for CHR-ERG-01"):
        add_products(_ready(app, order))


def test_unknown_product_cancels_and_hands_over_to_creation(order):
    app = _product_app([])
    with pytest.raises(NotBuiltYet, match="3.4-3.12"):
        add_products(_ready(app, order))
    assert app.calls[-1] == ("click", "select_product", "cancel")
