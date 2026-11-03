from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from image_to_cash.errors import Issue
from image_to_cash.extract.schema import OrderData
from image_to_cash.numbers import format_percent, money


def _vat_candidates(order: OrderData) -> set[Decimal]:
    per_line = sum((money(i.line_net * i.vat_pct / 100) for i in order.items), Decimal("0"))
    by_rate: dict[Decimal, Decimal] = defaultdict(Decimal)
    for i in order.items:
        by_rate[i.vat_pct] += i.line_net
    per_rate = sum((money(net * rate / 100) for rate, net in by_rate.items()), Decimal("0"))
    return {per_line, per_rate}


def validate(order: OrderData, *, expected_currency: str = "EUR") -> list[Issue]:
    issues: list[Issue] = []

    def error(field: str, message: str) -> None:
        issues.append(Issue("error", field, message))

    def warn(field: str, message: str) -> None:
        issues.append(Issue("warning", field, message))

    if order.currency != expected_currency.upper():
        error("order.currency", f"{order.currency} differs from Fakturama's currency {expected_currency}")

    seen_skus: set[str] = set()
    for idx, item in enumerate(order.items):
        p = f"items[{idx}] ({item.sku})"
        if item.quantity <= 0:
            error(p, f"quantity must be positive, got {item.quantity}")
        if item.unit_net_price < 0:
            error(p, f"unit net price is negative: {item.unit_net_price}")
        if not (0 <= item.discount_pct < 100):
            error(p, f"discount must be 0-99%, got {item.discount_pct}%")
        if not (0 <= item.vat_pct < 100):
            error(p, f"VAT must be 0-99%, got {item.vat_pct}%")
        if item.computed_line_net != item.line_net:
            error(
                p,
                f"{item.quantity} x {item.unit_net_price} x (1 - {format_percent(item.discount_pct)}%) "
                f"= {item.computed_line_net}, but the image says {item.line_net}",
            )
        if item.sku.casefold() in seen_skus:
            warn(p, "SKU appears on more than one line")
        seen_skus.add(item.sku.casefold())

    lines_sum = sum((i.line_net for i in order.items), Decimal("0"))
    if lines_sum != order.totals.net:
        error("totals.net", f"sum of lines is {lines_sum}, but the image says {order.totals.net}")
    vat_options = _vat_candidates(order)
    if order.totals.vat not in vat_options:
        shown = " or ".join(str(v) for v in sorted(vat_options))
        error("totals.vat", f"VAT computed from the lines is {shown}, but the image says {order.totals.vat}")
    if order.totals.net + order.totals.vat != order.totals.gross:
        error(
            "totals.gross",
            f"{order.totals.net} + {order.totals.vat} = {order.totals.net + order.totals.vat}, "
            f"but the image says {order.totals.gross}",
        )

    pay = order.payment
    if pay.is_paid and pay.payment_date is None:
        error("payment.payment_date", "status is PAID but no payment date is printed")
    if not pay.is_paid and pay.payment_date is not None:
        warn("payment.payment_date", f"status is {pay.paid_status}; the printed date is ignored (spec 5.3)")
    if pay.payment_date and pay.payment_date < order.order_date:
        warn("payment.payment_date", f"payment date {pay.payment_date} is before the order date {order.order_date}")

    return issues
