import pytest

from image_to_cash.extract.schema import Address, Debtor, Item
from image_to_cash.flow.matching import CREATE, REVIEW, SELECT, address_parts, decide_debtor, decide_product, text_contains
from tests.fakes import ADDRESS_COLUMNS, PRODUCT_COLUMNS, grid

DEBTOR = Debtor(company="Northstar Office GmbH", first_name="Marta", last_name="Klein")
BILLING = Address(name="Northstar Office GmbH", street="Friedrichstrasse 88", zip="10117", city="Berlin", country="Germany")
ITEM = Item(position=1, sku="CHR-ERG-01", description="Ergonomic Desk Chair", quantity=2, unit_net_price="250.00",
            discount_pct=10, vat_pct=19, line_net="450.00")
EXACT = ("CUST000001", "Marta", "Klein", "Northstar Office GmbH", "10117", "Berlin")


def _debtors(*rows):
    return decide_debtor(grid(ADDRESS_COLUMNS, *rows), DEBTOR, BILLING)


def test_one_exact_contact_is_selected():
    decision = _debtors(EXACT, ("CUST000002", "Jan", "Berg", "Other AG", "80331", "Munich"))
    assert decision.action == SELECT and decision.row.cells["No."] == "CUST000001"
    assert decision.truncated == ()


def test_ocr_lookalikes_and_cut_off_company_still_match():
    decision = _debtors(("CUST000001", "Marta", "Klein", "Northstar Offic...", "1O117", "Berlin"))
    assert decision.action == SELECT and decision.truncated == ("Company",)


def test_two_exact_contacts_need_review():
    decision = _debtors(EXACT, ("CUST000009",) + EXACT[1:])
    assert decision.action == REVIEW and "2 contacts match exactly" in decision.reason


def test_same_company_with_other_details_is_a_conflict():
    decision = _debtors(("CUST000001", "Marta", "Klein", "Northstar Office GmbH", "10553", "Berlin"))
    assert decision.action == REVIEW
    assert "ZIP '10553' (expected '10117')" in decision.reason


@pytest.mark.parametrize("rows", [(), (("CUST000002", "Jan", "Berg", "Other AG", "80331", "Munich"),)])
def test_no_related_contact_means_create(rows):
    assert _debtors(*rows).action == CREATE


def test_private_person_is_keyed_by_last_name():
    person = Debtor(company=None, first_name="Marta", last_name="Klein")
    rows = grid(ADDRESS_COLUMNS, ("CUST000001", "Max", "Klein", "", "10117", "Berlin"))
    decision = decide_debtor(rows, person, BILLING)
    assert decision.action == REVIEW and "same Name" in decision.reason


def _products(*rows):
    return decide_product(grid(PRODUCT_COLUMNS, *rows), ITEM)


def test_exact_sku_with_its_name_is_selected():
    decision = _products(("CHR-ERG-01", "Ergonomic Desk Chair", "Ergonomic Desk Chair", "0", "$297.50", "VAT 19%"))
    assert decision.action == SELECT and decision.truncated == ()


def test_cut_off_product_name_is_selected_but_marked():
    decision = _products(("CHR-ERG-0I", "Ergonomic Desk Ch...", "", "0", "$297.50", "VAT 19%"))
    assert decision.action == SELECT and decision.truncated == ("Name",)


def test_same_sku_with_another_name_is_a_conflict():
    decision = _products(("CHR-ERG-01", "Standing Desk", "", "0", "$500.00", "VAT 19%"))
    assert decision.action == REVIEW and "differs" in decision.reason


def test_similar_but_different_sku_means_create():
    assert _products(("CHR-ERG-010", "Ergonomic Desk Chair", "", "0", "$1.00", "VAT 19%")).action == CREATE


def test_two_products_with_the_sku_need_review():
    row = ("CHR-ERG-01", "Ergonomic Desk Chair", "", "0", "$297.50", "VAT 19%")
    assert _products(row, row).action == REVIEW


def test_address_parts_and_contains():
    parts = dict(address_parts(BILLING, DEBTOR))
    assert parts == {"name": "Northstar Office GmbH", "contact": "Marta Klein", "street": "Friedrichstrasse 88",
                     "ZIP": "10117", "City": "Berlin"}
    shown = "Northstar Office GmbH\nMarta Klein\nFriedrichstrasse 88\nDE-10117 Berlin\nGermany"
    assert all(text_contains(shown, v) for v in parts.values())
    assert not text_contains(shown, "Beusselstrasse 44")
