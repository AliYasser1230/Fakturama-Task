from datetime import date
from decimal import Decimal

import pytest

from image_to_cash.extract.normalize import normalize, parse_date, split_contact_name
from image_to_cash.extract.schema import OrderData, PaymentMethod


def _errors(issues):
    return {i.field for i in issues if i.level == "error"}


def test_sample_normalizes_to_expected_values(raw):
    order, issues = normalize(raw)
    assert order is not None and not _errors(issues)

    assert order.external_reference == "WEB-2026-0714-A17"
    assert order.order_date == date(2026, 7, 14)
    assert order.currency == "EUR"

    d = order.debtor
    assert (d.company, d.first_name, d.last_name) == ("Northstar Office GmbH", "Marta", "Klein")
    assert d.salutation is None
    assert d.alias == "NORTHSTAR-BERLIN"
    assert d.search_text == "Northstar Office GmbH"

    assert order.billing_address.street == "Friedrichstrasse 88"
    assert order.delivery_address.zip == "10553"
    assert order.delivery_same_as_billing is False

    assert order.payment.method is PaymentMethod.BANK_TRANSFER
    assert order.payment.method.payment_code == "Credit transfer"
    assert order.payment.is_paid and order.payment.payment_date == date(2026, 7, 18)

    chair, mat = order.items
    assert (chair.sku, chair.quantity, chair.discount_pct, chair.vat_pct) == ("CHR-ERG-01", 2, 10, 19)
    assert chair.vat_name == "VAT 19%"
    assert chair.gross_unit_price == Decimal("297.50")
    assert mat.gross_unit_price == Decimal("47.60")
    assert chair.computed_line_net == Decimal("450.00")
    assert mat.computed_line_net == Decimal("120.00")

    assert (order.totals.net, order.totals.vat, order.totals.gross) == (
        Decimal("570.00"), Decimal("108.30"), Decimal("678.30"))


def test_sample_matches_committed_expected_json(raw, sample_expected_path):
    order, _ = normalize(raw)
    assert order == OrderData.model_validate_json(sample_expected_path.read_text())


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-07-14", date(2026, 7, 14)),
        ("14.07.2026", date(2026, 7, 14)),
        ("14 July 2026", date(2026, 7, 14)),
        ("Jul 14, 2026", date(2026, 7, 14)),
        ("14/07/2026", date(2026, 7, 14)),
        ("07/14/2026", date(2026, 7, 14)),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["03/04/2026", "2026/13/01", "yesterday", ""])
def test_parse_date_rejects_ambiguous_or_unknown(text):
    with pytest.raises(ValueError):
        parse_date(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Marta Klein", (None, "Marta", "Klein")),
        ("Ms. Marta Klein", ("Ms.", "Marta", "Klein")),
        ("Herr Max Mustermann", ("Mr.", "Max", "Mustermann")),
        ("Klein", (None, None, "Klein")),
        (None, (None, None, None)),
    ],
)
def test_split_contact_name(text, expected):
    assert split_contact_name(text) == expected


def test_three_part_name_is_an_error_not_a_guess(raw):
    raw.customer.contact_name = "Jan van der Berg"
    order, issues = normalize(raw)
    assert order is None and "customer.contact_name" in _errors(issues)


def test_missing_delivery_address_reuses_billing_with_warning(raw):
    raw.delivery_address = None
    order, issues = normalize(raw)
    assert order is not None and order.delivery_same_as_billing
    assert any(i.field == "delivery_address" and i.level == "warning" for i in issues)


def test_unknown_payment_method_is_rejected(raw):
    raw.payment.method = "PayPal"
    order, issues = normalize(raw)
    assert order is None and "payment.method" in _errors(issues)


def test_payment_method_case_insensitive(raw):
    raw.payment.method = "bank transfer"
    order, _ = normalize(raw)
    assert order.payment.method is PaymentMethod.BANK_TRANSFER


def test_unreadable_field_is_rejected(raw):
    raw.unreadable_fields = ["items[0].unit_net_price"]
    order, issues = normalize(raw)
    assert order is None and "items[0].unit_net_price" in _errors(issues)


def test_order_level_discount_or_shipping_is_rejected(raw):
    raw.totals.shipping = "EUR 9.90"
    order, issues = normalize(raw)
    assert order is None and "totals.shipping" in _errors(issues)


@pytest.mark.parametrize("value", ["0.00", "0%", "Free of shipping costs"])
def test_zero_or_free_order_level_values_are_fine(raw, value):
    raw.totals.shipping = value
    raw.totals.order_discount = "0%"
    order, issues = normalize(raw)
    assert order is not None and not _errors(issues)


def test_missing_required_fields_are_all_reported(raw):
    raw.order.external_reference = None
    raw.billing_address.zip = "  "
    raw.items[1].sku = None
    order, issues = normalize(raw)
    assert order is None
    assert {"order.external_reference", "billing_address.zip", "items[1].sku"} <= _errors(issues)


def test_not_paid_status(raw):
    raw.payment.paid_status = "unpaid"
    raw.payment.payment_date = None
    order, _ = normalize(raw)
    assert order.payment.paid_status == "UNPAID" and not order.payment.is_paid
