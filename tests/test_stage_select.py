from decimal import Decimal

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
    assert ("search", "select_address", "Northstar Office GmbH") in app.calls
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


def test_unknown_contact_is_created_saved_once_and_reselected(order):
    app = FakeApp(tables={("select_address", "table"): grid(ADDRESS_COLUMNS)})
    result = select_debtor(_ready(app, order))
    assert result.ok, [str(c) for c in result.checks if not c.ok]
    steps = [("click", "select_address", "cancel"), ("save", "payment_editor", "Bank Transfer"),
             ("click", "main", "nav_new_contact"), ("save", "debtor_editor", "Northstar Office GmbH"),
             ("click", "select_address", "ok")]
    positions = [app.calls.index(s) for s in steps]
    assert positions == sorted(positions)
    assert [s for s in app.saved if s[0] == "debtor_editor"] == [("debtor_editor", "Northstar Office GmbH")]
    whats = {c.what for c in result.checks}
    assert {"new contact reselected in the order", "Invoice address street", "Delivery address street"} <= whats
    assert any("created contact CUST000001" in n for n in result.notes)


def test_saved_contact_missing_from_the_selector_needs_review(order):
    app = FakeApp(tables={("select_address", "table"): grid(ADDRESS_COLUMNS)})
    real_save = app.save

    def save_without_listing(screen, title=None, *, saved_title=None, timeout=None):
        name = real_save(screen, title, saved_title=saved_title, timeout=timeout)
        if screen == "debtor_editor":
            app.tables[("select_address", "table")] = grid(ADDRESS_COLUMNS)
        return name

    app.save = save_without_listing
    with pytest.raises(ManualReviewRequired, match="does not show it"):
        select_debtor(_ready(app, order))


def _product_app(rows):
    return FakeApp(tables={("select_product", "table"): grid(PRODUCT_COLUMNS, *rows)})


EXISTING = [("CHR-ERG-01", "Ergonomic Desk Chair", "Ergonomic Desk Chair", "0", "$297.50", "VAT 19%"),
            ("MAT-DESK-02", "Anti-Fatigue Desk Mat", "Anti-Fatigue Desk Mat", "0", "$47.60", "VAT 19%")]


def test_existing_products_are_selected_and_their_lines_completed_in_source_order(order):
    app = _product_app(EXISTING)
    result = add_products(_ready(app, order))
    assert result.ok, [str(c) for c in result.checks if not c.ok]
    searches = [c[2] for c in app.calls if c[:2] == ("search", "select_product")]
    assert searches == ["CHR-ERG-01", "MAT-DESK-02"]
    assert app.saved == []
    edits = [c[1:] for c in app.calls if c[0] == "set_line_cell"]
    assert edits == [("CHR-ERG-01", "Qty.", "2"), ("CHR-ERG-01", "U.Price", "250.00"), ("CHR-ERG-01", "Discount", "10"),
                     ("MAT-DESK-02", "Qty.", "3"), ("MAT-DESK-02", "U.Price", "40.00"), ("MAT-DESK-02", "Discount", "0")]
    first_mat = app.calls.index(("search", "select_product", "MAT-DESK-02"))
    assert app.calls.index(("set_line_cell", "CHR-ERG-01", "Discount", "10")) < first_mat
    totals = {c.what.split(" (")[0]: c.shown for c in result.checks if c.what.startswith(("Total Net", "VAT after"))}
    assert totals == {"Total Net after CHR-ERG-01": "$450.00", "VAT after CHR-ERG-01": "$85.50",
                      "Total Net after MAT-DESK-02": "$570.00", "VAT after MAT-DESK-02": "$108.30"}


def test_missing_products_get_the_vat_and_are_created_saved_and_selected(order):
    app = _product_app([])
    result = add_products(_ready(app, order))
    assert app.saved == [("vat_editor", "VAT 19%"), ("product_editor", "Ergonomic Desk Chair"),
                         ("product_editor", "Anti-Fatigue Desk Mat")]
    assert all(c.ok for c in result.checks), [str(c) for c in result.checks if not c.ok]
    gross = [c.shown for c in result.checks if c.what.startswith("stored Price (gross)")]
    assert gross == ["297.50", "47.60"]
    assert ("click_row", {"Standard": "", "Name": "VAT 19%", "Description": "VAT 19%", "Value": "19.00 %"}, True) in app.calls


def test_a_total_that_does_not_add_up_stops_the_stage(order):
    from image_to_cash.flow.runner import GateFailed

    app = _product_app([("CHR-ERG-01", "Ergonomic Desk Chair", "Ergonomic Desk Chair", "0", "$297.50", "VAT 7%")] + EXISTING[1:])
    with pytest.raises(GateFailed) as exc:
        add_products(_ready(app, order))
    assert [c.what.split(" (")[0] for c in exc.value.result.checks if not c.ok] == ["VAT after CHR-ERG-01"]


def test_selected_product_without_a_new_line_needs_review(order):
    app = _product_app(EXISTING)
    app.on_ok = {"select_product": {("order_editor", "items"): grid(ITEM_COLUMNS)}}
    with pytest.raises(ManualReviewRequired, match="order line for CHR-ERG-01"):
        add_products(_ready(app, order))


def test_conflicting_product_cancels_and_asks_for_review(order):
    app = _product_app([("CHR-ERG-01", "Standing Desk", "", "0", "$500.00", "VAT 19%")])
    with pytest.raises(ManualReviewRequired, match="differs"):
        add_products(_ready(app, order))
    assert app.saved == [] and "select_product" not in app.open


def test_delivery_address_may_show_the_company_instead_of_its_own_name(order):
    company_delivery = "Northstar Office GmbH\nMarta Klein\nBeusselstrasse 44\nDE-10553 Berlin\nGermany"
    app = _address_app([CONTACT_ROW], delivery=company_delivery)
    result = select_debtor(_ready(app, order))
    name = next(c for c in result.checks if c.what.startswith("Delivery address name"))
    assert name.ok and "Fakturama prints the company" in name.what


def test_delivery_address_with_another_street_still_fails(order):
    other = "Northstar Office GmbH\nMarta Klein\nHafenweg 1\nDE-10553 Berlin\nGermany"
    app = _address_app([CONTACT_ROW], delivery=other)
    with pytest.raises(GateFailed) as exc:
        select_debtor(_ready(app, order))
    assert [c.what for c in exc.value.result.checks if not c.ok] == ["Delivery address street"]


def test_fakturama_selecting_the_right_product_itself_is_accepted(order):
    app = _product_app(EXISTING)
    app.auto_select["select_product"] = dict(zip(PRODUCT_COLUMNS, EXISTING[0]))
    with pytest.raises(ManualReviewRequired, match="order line for MAT-DESK-02"):
        add_products(_ready(app, order))
    assert app.line_data[0]["sku"] == "CHR-ERG-01"
    assert ("click", "select_product", "cancel") not in app.calls


def test_fakturama_selecting_a_wrong_product_itself_stops_for_review(order):
    wrong = ("CHR-ERG-010", "Ergonomic Desk Chair XL", "", "0", "$300.00", "VAT 19%")
    app = _product_app([wrong])
    app.auto_select["select_product"] = dict(zip(PRODUCT_COLUMNS, wrong))
    with pytest.raises(ManualReviewRequired, match="order line for CHR-ERG-01"):
        add_products(_ready(app, order))
    assert app.saved == []


def test_fakturama_selecting_a_wrong_contact_itself_fails_the_address_check(order):
    app = _address_app([], invoice="Other GmbH\nJan Berg\nHauptstrasse 1\nDE-80331 Munich\nGermany")
    app.auto_select["select_address"] = {"No.": "CUST000009"}
    with pytest.raises(GateFailed) as exc:
        select_debtor(_ready(app, order))
    assert "Invoice address street" in [c.what for c in exc.value.result.checks if not c.ok]


def test_an_existing_vat_with_another_code_stops_for_review(order):
    from image_to_cash.flow.vat import ensure_vat

    app = FakeApp(tables={("vats_list", "table"): grid(("Standard", "Name", "Description", "Value"),
                                                       ("", "VAT 19%", "VAT 19%", "19.00 %"))})
    app.vat_codes["VAT 19%"] = "AE (Reverse charge)"
    with pytest.raises(ManualReviewRequired, match="VAT code is 'AE"):
        ensure_vat(app, Decimal("19"))
    assert not any(s[0] == "vat_editor" for s in app.saved)
