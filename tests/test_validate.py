from datetime import date
from decimal import Decimal

import pytest

from image_to_cash.extract.normalize import normalize
from image_to_cash.extract.validate import validate


@pytest.fixture
def order(raw):
    order, issues = normalize(raw)
    assert order is not None, issues
    return order


def _errors(issues):
    return {i.field.split(" ")[0] for i in issues if i.level == "error"}


def test_sample_passes_all_checks(order):
    assert validate(order) == []


def test_wrong_line_total_is_caught(order):
    order.items[0].line_net = Decimal("500.00")  # discount not applied
    issues = validate(order)
    assert "items[0]" in _errors(issues)
    assert any("450.00" in i.message for i in issues)


def test_wrong_net_vat_gross_are_caught(order):
    order.totals.net = Decimal("575.00")
    order.totals.vat = Decimal("108.00")
    order.totals.gross = Decimal("678.00")
    assert {"totals.net", "totals.vat", "totals.gross"} <= _errors(validate(order))


def test_vat_rounded_per_rate_or_per_line_both_accepted(order):
    # 3 x 0.35 at 19%: per line 0.07 x 3 = 0.21, per rate round(1.05 x 0.19) = 0.20
    for item in order.items:
        item.quantity, item.unit_net_price, item.discount_pct = Decimal("1"), Decimal("0.35"), Decimal("0")
        item.line_net = Decimal("0.35")
    order.items.append(order.items[0].model_copy(update={"sku": "X-3", "position": 3}))
    order.totals.net = Decimal("1.05")
    for vat in ("0.20", "0.21"):
        order.totals.vat = Decimal(vat)
        order.totals.gross = order.totals.net + order.totals.vat
        assert validate(order) == [], vat


def test_paid_without_date_is_an_error(order):
    order.payment.payment_date = None
    assert "payment.payment_date" in _errors(validate(order))


def test_unpaid_with_date_only_warns(order):
    order.payment.paid_status = "OPEN"
    issues = validate(order)
    assert not _errors(issues)
    assert any(i.field == "payment.payment_date" and i.level == "warning" for i in issues)


def test_payment_before_order_date_warns(order):
    order.payment.payment_date = date(2026, 7, 1)
    issues = validate(order)
    assert not _errors(issues) and any(i.level == "warning" for i in issues)


def test_currency_must_match_fakturama(order):
    assert "order.currency" in _errors(validate(order, expected_currency="USD"))


@pytest.mark.parametrize(
    "field, value",
    [("quantity", "0"), ("unit_net_price", "-1"), ("discount_pct", "100"), ("vat_pct", "150")],
)
def test_out_of_range_item_values(order, field, value):
    setattr(order.items[1], field, Decimal(value))
    assert "items[1]" in _errors(validate(order))


def test_duplicate_sku_only_warns(order):
    order.items[1].sku = "chr-erg-01"
    issues = validate(order)
    assert any(i.level == "warning" and "SKU" in i.message for i in issues)
