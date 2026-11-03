from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from image_to_cash.extract.schema import Item
from image_to_cash.flow.runner import Check
from image_to_cash.numbers import format_percent, money, parse_amount

EDITOR = "order_editor"
TABLE = "items"


def quantity_text(quantity: Decimal) -> str:
    return format(quantity.normalize(), "f")


def number(shown: str) -> Decimal | None:
    text = (shown or "").replace("%", "").strip()
    try:
        return parse_amount(text)
    except ValueError:
        try:
            return Decimal(text)
        except InvalidOperation:
            return None


def equals(value: Decimal):
    return lambda shown: number(shown) == value


def net_total(items: list[Item]) -> Decimal:
    return money(sum((i.computed_line_net for i in items), Decimal("0")))


def vat_totals(items: list[Item]) -> set[Decimal]:
    per_line = money(sum((money(i.computed_line_net * i.vat_pct / 100) for i in items), Decimal("0")))
    by_rate: dict[Decimal, Decimal] = defaultdict(Decimal)
    for i in items:
        by_rate[i.vat_pct] += i.computed_line_net
    per_rate = money(sum((money(net * rate / 100) for rate, net in by_rate.items()), Decimal("0")))
    return {per_line, per_rate}


def complete_line(app, item: Item, done: list[Item]) -> list[Check]:
    sku = item.sku
    quantity = quantity_text(item.quantity)
    unit = f"{item.unit_net_price:.2f}"
    discount = format_percent(item.discount_pct)
    shown_qty = app.set_line_cell(EDITOR, TABLE, sku, "Qty.", quantity, check=equals(item.quantity), left_of_key=True)
    shown_unit = app.set_line_cell(EDITOR, TABLE, sku, "U.Price", unit, check=equals(money(item.unit_net_price)))
    shown_discount = app.set_line_cell(EDITOR, TABLE, sku, "Discount", discount, check=equals(item.discount_pct))

    lines = done + [item]
    expected_net = net_total(lines)
    vat_options = vat_totals(lines)
    shown_net = app.read(EDITOR, "subtotal")
    shown_vat = app.read(EDITOR, "vat_total")
    return [
        Check(f"line {sku} Qty.", quantity, shown_qty, number(shown_qty) == item.quantity),
        Check(f"line {sku} U.Price", unit, shown_unit, number(shown_unit) == money(item.unit_net_price)),
        Check(f"line {sku} Discount", f"{discount}%", shown_discount, number(shown_discount) == item.discount_pct),
        Check(f"Total Net after {sku} (line Price {item.computed_line_net} = qty x unit x (1 - discount))",
              str(expected_net), shown_net, number(shown_net) == expected_net),
        Check(f"VAT after {sku} ({format_percent(item.vat_pct)}% on the lines)",
              " or ".join(sorted(str(v) for v in vat_options)), shown_vat, number(shown_vat) in vat_options),
    ]
