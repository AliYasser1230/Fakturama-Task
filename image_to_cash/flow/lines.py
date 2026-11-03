from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from image_to_cash.extract.schema import Item
from image_to_cash.flow.runner import Check
from image_to_cash.numbers import format_percent, money, parse_amount
from image_to_cash.ui.grid_ocr import GridRow, cell_matches, cell_word, line_row

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


MONEY_CELL = re.compile(r"[$Ss]?[\d.,oO]*\d[\d.,oO]*")
MONEY_LOOKALIKES = str.maketrans({"o": "0", "O": "0", "S": "$", "s": "$"})


def cell_amount(shown: str) -> Decimal | None:
    text = "".join((shown or "").split())
    if MONEY_CELL.fullmatch(text):
        return number(text.translate(MONEY_LOOKALIKES))
    return number(shown)


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


def checked_cell(app, screen: str, control: str, row: GridRow, column: str, ok,
                 title: str | None = None) -> tuple[str, bool]:
    shown = row.cells.get(column, "")
    if ok(shown):
        return shown, True
    again = app.read_cell(screen, control, row, column, title)
    return f"{shown!r}, re-read {again!r}", ok(again)


def quantity_left_of_sku(app, screen: str, row: GridRow, item: Item, title: str | None) -> tuple[str, bool]:
    shown = row.cells.get("Qty.", "")
    if number(shown) == item.quantity:
        return shown, True
    rows = app.table_rows(screen, TABLE, title)
    line = line_row(rows, item.sku)
    word = cell_word(rows, line, "Qty.", key=item.sku, left_of_key=True) if line else None
    again = word.text if word else ""
    return (f"{shown!r}, re-read {again!r}" if shown else again), number(again) == item.quantity


def line_checks(app, screen: str, items: list[Item], label: str, title: str | None = None) -> list[Check]:
    with app.revealed(screen, TABLE, title):
        return _line_checks(app, screen, items, label, title)


def _line_checks(app, screen: str, items: list[Item], label: str, title: str | None) -> list[Check]:
    grid = app.read_table(screen, TABLE, title, required=("Item No.", "Name", "U.Price"))
    lines = [r for r in grid.rows if r.cells.get("Item No.", "").strip()]
    shown = ", ".join(r.cells["Item No."] for r in lines) or "no lines"
    checks = [Check(f"{label} lines", str(len(items)), shown, len(lines) == len(items))]
    for item in sorted(items, key=lambda i: i.position):
        found = [r for r in lines if cell_matches(r.cells["Item No."], item.sku)]
        if len(found) != 1:
            checks.append(Check(f"{label} line {item.sku}", "one line", f"{len(found)} lines", False))
            continue
        row = found[0]
        name = row.cells.get("Name", "")
        unit = money(item.unit_net_price)
        qty_shown, qty_ok = quantity_left_of_sku(app, screen, row, item, title)
        unit_shown, unit_ok = checked_cell(app, screen, TABLE, row, "U.Price", lambda s: cell_amount(s) == unit,
                                           title)
        checks += [
            Check(f"{label} line {item.sku} Name", item.description, name, cell_matches(name, item.description) is not None),
            Check(f"{label} line {item.sku} Qty.", quantity_text(item.quantity), qty_shown, qty_ok),
            Check(f"{label} line {item.sku} U.Price", str(unit), unit_shown, unit_ok),
        ]
    return checks
