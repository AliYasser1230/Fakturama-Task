from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.flow.debtor import address_checks
from image_to_cash.flow.documents import document_checks, document_row
from image_to_cash.flow.lines import equals, line_checks, number
from image_to_cash.flow.runner import Check, RunContext, StageResult, gate
from image_to_cash.flow.save_order import totals_checks
from image_to_cash.ui.actions import parse_display_date, same_text

INVOICE = "invoice_editor"
STAGE = ("5", "Complete and verify the linked Invoice")


def copied_checks(app, ctx: RunContext) -> list[Check]:
    order = ctx.order
    read = lambda control: app.read(INVOICE, control)
    order_date = read("order_date")
    return [
        Check("invoice Cust.Ref. (copied)", order.external_reference, read("cust_ref"),
              same_text(read("cust_ref"), order.external_reference)),
        Check("invoice Order Date (copied)", order.order_date.isoformat(), order_date,
              parse_display_date(order_date) == order.order_date),
        Check("invoice VAT mode (copied)", "With VAT", read("vat_mode"), same_text(read("vat_mode"), "With VAT")),
        Check("invoice price mode (copied)", "Net", read("price_mode"), same_text(read("price_mode"), "Net")),
    ] + address_checks(app, order, INVOICE) + line_checks(app, INVOICE, order.items, "invoice (copied)") + \
        totals_checks(app, order.totals, INVOICE, "invoice (copied)")


def payment_checks(app, ctx: RunContext, title: str | None = None) -> list[Check]:
    order = ctx.order
    method = order.payment.method.value
    shown = app.read(INVOICE, "payment", title)
    paid = app.is_ticked(INVOICE, "paid", title)
    checks = [Check("invoice payment method", method, shown, same_text(shown, method)),
              Check("invoice paid", "ticked" if order.payment.is_paid else "clear",
                    "ticked" if paid else "clear", paid == order.payment.is_paid)]
    if order.payment.is_paid:
        when = app.read(INVOICE, "paid_date", title)
        value = app.read(INVOICE, "paid_value", title)
        checks += [Check("invoice payment date", order.payment.payment_date.isoformat(), when,
                         parse_display_date(when) == order.payment.payment_date),
                   Check("invoice paid Value = invoice Total", str(order.totals.gross), value,
                         number(value) == order.totals.gross)]
    return checks


def complete_invoice(ctx: RunContext) -> StageResult:
    app, order = ctx.app, ctx.order
    app.activate(INVOICE)
    ctx.invoice_number = app.read(INVOICE, "number")
    proposed = {c: app.read(INVOICE, c) for c in ("number", "date", "service_date")}
    checks = copied_checks(app, ctx)

    method = order.payment.method.value
    if not same_text(app.read(INVOICE, "payment"), method):
        if not [o for o in app.options(INVOICE, "payment") if same_text(o, method)]:
            raise ManualReviewRequired(f"the invoice's payment list does not offer {method!r}")
        app.choose(INVOICE, "payment", method)
    if order.payment.is_paid:
        app.tick(INVOICE, "paid", True)
        app.wait_for(INVOICE, "paid_value")
        app.set_date(INVOICE, "paid_date", order.payment.payment_date)
        app.type(INVOICE, "paid_value", f"{order.totals.gross:.2f}", check=equals(order.totals.gross))
    elif app.is_ticked(INVOICE, "paid"):
        app.tick(INVOICE, "paid", False)
    checks += payment_checks(app, ctx)
    checks += [Check(f"invoice {c} (proposed, unchanged)", v, app.read(INVOICE, c), same_text(app.read(INVOICE, c), v))
               for c, v in proposed.items()]
    gate(*STAGE, checks)

    saved = app.save(INVOICE)
    checks.append(Check("invoice saved", ctx.invoice_number, saved, True))
    checks += [Check(f"stored {c.what}", c.expected, c.shown, c.ok) for c in payment_checks(app, ctx, title=saved)]

    invoice_date = parse_display_date(proposed["date"])
    state = "paid" if order.payment.is_paid else "open"
    checks += document_checks(app, document_row(app, ctx.invoice_number, "invoices"), label="Invoice",
                              document=ctx.invoice_number, when=invoice_date, cust_ref=order.external_reference,
                              state=state, total=order.totals.gross)
    checks += document_checks(app, document_row(app, ctx.order_number, "orders"), label="Order (still open)",
                              document=ctx.order_number, when=order.order_date, cust_ref=order.external_reference,
                              state="open", total=order.totals.gross)
    return gate(*STAGE, checks, notes=[f"invoice {ctx.invoice_number} saved as {saved!r}; flow ends here (task 5.7)"])
