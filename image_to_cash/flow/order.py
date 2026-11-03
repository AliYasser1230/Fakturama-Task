from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired, VerificationFailed
from image_to_cash.flow.runner import Check, RunContext, StageResult, gate
from image_to_cash.ui.actions import parse_display_date, same_text

EDITOR = "order_editor"
NET = "Net"
WITH_VAT = "With VAT"


def open_order(ctx: RunContext) -> StageResult:
    app, order = ctx.app, ctx.order
    if app.editor_open(EDITOR):
        raise ManualReviewRequired("a New Order editor is already open in Fakturama; save or close it, then run again")

    app.click("main", "new_order")
    app.wait_open(EDITOR)
    number = app.read(EDITOR, "number")
    if not number.strip():
        raise VerificationFailed("the New Order has no proposed No.")

    app.set_date(EDITOR, "date", order.order_date)
    app.type(EDITOR, "cust_ref", order.external_reference)
    app.choose(EDITOR, "price_mode", NET)
    if not same_text(app.read(EDITOR, "vat_mode"), WITH_VAT):
        app.choose(EDITOR, "vat_mode", WITH_VAT)
    ctx.order_number = number

    shown = {c: app.read(EDITOR, c) for c in ("number", "date", "cust_ref", "price_mode", "vat_mode")}
    checks = [
        Check("No. (proposed, unchanged)", number, shown["number"], same_text(shown["number"], number)),
        Check("Date", order.order_date.isoformat(), shown["date"], parse_display_date(shown["date"]) == order.order_date),
        Check("Cust.Ref.", order.external_reference, shown["cust_ref"], same_text(shown["cust_ref"], order.external_reference)),
        Check("price mode", NET, shown["price_mode"], same_text(shown["price_mode"], NET)),
        Check("VAT", WITH_VAT, shown["vat_mode"], same_text(shown["vat_mode"], WITH_VAT)),
        Check("New Order tab still open", "open", "open" if app.is_open(EDITOR) else "closed", app.is_open(EDITOR)),
    ]
    return gate("1", "Open the New Order", checks, notes=[f"Fakturama proposed No. {number}"])
