from __future__ import annotations

from decimal import Decimal

from image_to_cash.flow.debtor import address_checks
from image_to_cash.flow.documents import document_checks, document_row
from image_to_cash.flow.lines import line_checks, number
from image_to_cash.flow.runner import Check, RunContext, StageResult, gate
from image_to_cash.ui.actions import same_text

EDITOR = "order_editor"
INVOICE = "invoice_editor"
STAGE = ("4", "Complete and save the Order")
FREE_SHIPPING = "Free of shipping costs"


def amount_check(what: str, expected: Decimal, shown: str) -> Check:
    return Check(what, str(expected), shown, number(shown) == expected)


def totals_checks(app, totals, screen: str, label: str, title: str | None = None) -> list[Check]:
    return [
        amount_check(f"{label} Total Net", totals.net, app.read(screen, "subtotal", title)),
        amount_check(f"{label} VAT", totals.vat, app.read(screen, "vat_total", title)),
        amount_check(f"{label} Total", totals.gross, app.read(screen, "total", title)),
    ]


def save_order(ctx: RunContext) -> StageResult:
    app, order = ctx.app, ctx.order
    app.activate(EDITOR)
    shipping = app.read(EDITOR, "shipping")
    checks = address_checks(app, order) + line_checks(app, EDITOR, order.items, "order") + [
        Check("order Discount", "0%", app.read(EDITOR, "discount"), number(app.read(EDITOR, "discount")) == 0),
        Check("Shipping", FREE_SHIPPING, shipping, same_text(shipping, FREE_SHIPPING)),
        amount_check("Shipping amount", Decimal("0.00"), app.read(EDITOR, "shipping_amount")),
    ] + totals_checks(app, order.totals, EDITOR, "order")
    gate(*STAGE, checks)

    saved = app.save(EDITOR)
    ctx.order_title = saved
    checks.append(Check("order saved", ctx.order_number or "", saved, True))
    row = document_row(app, ctx.order_number)
    checks += document_checks(app, row, label="Order", document=ctx.order_number, when=order.order_date,
                              cust_ref=order.external_reference, state="open", total=order.totals.gross)
    gate(*STAGE, checks)

    app.activate(EDITOR, title=saved)
    app.click(EDITOR, "create_invoice", title=saved)
    app.wait_open(INVOICE)
    checks.append(Check("linked New Invoice opened from the Order's follow-up Invoice", "open", "open", True))
    return gate(*STAGE, checks, notes=[f"order {ctx.order_number} saved as {saved!r}"])
