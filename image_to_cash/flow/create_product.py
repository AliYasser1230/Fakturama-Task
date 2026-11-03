from __future__ import annotations

from decimal import Decimal

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import Item
from image_to_cash.flow.runner import Check, gate
from image_to_cash.flow.vat import vat_name
from image_to_cash.numbers import money, parse_amount
from image_to_cash.ui.actions import same_text

EDITOR = "product_editor"
STAGE = ("3", "Select or create each Product")
UNTOUCHED = ("category", "gtin", "supplier_code")


def amount_is(shown: str, expected: Decimal) -> bool:
    try:
        return parse_amount(shown) == money(expected)
    except ValueError:
        return False


def product_checks(app, item: Item, title: str | None = None) -> list[Check]:
    read = lambda control: app.read(EDITOR, control, title=title)
    gross = item.gross_unit_price
    shown = {c: read(c) for c in ("item_number", "name", "description", "price_gross", "cost_price_net", "vat",
                                  "stock", *UNTOUCHED)}
    return [
        Check("Item Number", item.sku, shown["item_number"], same_text(shown["item_number"], item.sku)),
        Check("product Name", item.description, shown["name"], same_text(shown["name"], item.description)),
        Check("product Description", item.description, shown["description"],
              same_text(shown["description"], item.description)),
        Check("Price (gross) = unit net x (1 + VAT)", str(gross), shown["price_gross"], amount_is(shown["price_gross"], gross)),
        Check("cost price (net)", "0.00", shown["cost_price_net"], amount_is(shown["cost_price_net"], Decimal("0"))),
        Check("product VAT", vat_name(item.vat_pct), shown["vat"], same_text(shown["vat"], vat_name(item.vat_pct))),
        Check("Stock", "0.00", shown["stock"], amount_is(shown["stock"], Decimal("0"))),
        *[Check(f"{c} left blank", "", shown[c], shown[c].strip() == "") for c in UNTOUCHED],
    ]


def create_product(app, item: Item) -> list[Check]:
    if app.editor_open(EDITOR):
        raise ManualReviewRequired("a New product editor is already open in Fakturama; save or close it, then run again")
    app.click("main", "nav_new_product")
    app.wait_open(EDITOR)
    vat = vat_name(item.vat_pct)
    if [o for o in app.options(EDITOR, "vat") if same_text(o, vat)] == []:
        raise ManualReviewRequired(f"the product VAT list does not offer {vat!r}")
    app.type(EDITOR, "item_number", item.sku)
    app.type(EDITOR, "name", item.description)
    app.type(EDITOR, "description", item.description, commit="")
    gross = item.gross_unit_price
    app.type(EDITOR, "price_gross", f"{gross:.2f}", check=lambda shown: amount_is(shown, gross))
    app.type(EDITOR, "cost_price_net", "0.00", check=lambda shown: amount_is(shown, Decimal("0")))
    app.choose(EDITOR, "vat", vat)
    app.type(EDITOR, "stock", "0.00", check=lambda shown: amount_is(shown, Decimal("0")))
    checks = product_checks(app, item)
    gate(*STAGE, checks)
    saved = app.save(EDITOR)
    stored = product_checks(app, item, title=saved)
    return checks + [Check("product saved", item.description, saved, True)] + [
        Check(f"stored {c.what}", c.expected, c.shown, c.ok) for c in stored]
