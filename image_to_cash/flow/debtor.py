from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired, NotBuiltYet
from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.matching import CREATE, REVIEW, SELECT, Decision, address_parts, decide_debtor, text_contains
from image_to_cash.flow.runner import Check, RunContext, StageResult, gate

EDITOR = "order_editor"
DIALOG = "select_address"
STAGE = ("2", "Select or create the Debtor")


def search_debtor(app, order: OrderData) -> Decision:
    app.click(EDITOR, "select_address")
    app.wait_open(DIALOG)
    app.type(DIALOG, "search", order.debtor.search_text, commit="")
    grid = app.read_table_stable(DIALOG, "table")
    return decide_debtor(grid, order.debtor, order.billing_address)


def choose_row(app, decision: Decision) -> None:
    app.click_row(decision.row)
    app.click(DIALOG, "ok")
    app.wait_closed(DIALOG)


def cancel(app) -> None:
    app.click(DIALOG, "cancel")
    app.wait_closed(DIALOG)


def address_checks(app, order: OrderData) -> list[Check]:
    checks = []
    if app.exists(EDITOR, "tab_invoice_address"):
        app.click(EDITOR, "tab_invoice_address")
    invoice = app.read(EDITOR, "address")
    for label, value in address_parts(order.billing_address, order.debtor):
        checks.append(Check(f"Invoice address {label}", value, " / ".join(invoice.splitlines()),
                            text_contains(invoice, value)))

    if app.exists(EDITOR, "tab_delivery_address"):
        app.click(EDITOR, "tab_delivery_address")
        delivery = app.read(EDITOR, "delivery_address")
        for label, value in address_parts(order.delivery_address):
            checks.append(Check(f"Delivery address {label}", value, " / ".join(delivery.splitlines()),
                                text_contains(delivery, value)))
        app.click(EDITOR, "tab_invoice_address")
    else:
        same = order.delivery_same_as_billing
        checks.append(Check("Delivery address", "same as the invoice address" if same else order.delivery_address.street,
                            "no separate Delivery address tab", same))
    return checks


def select_debtor(ctx: RunContext) -> StageResult:
    app, order = ctx.app, ctx.order
    decision = search_debtor(app, order)
    if decision.action == SELECT:
        choose_row(app, decision)
        notes = [decision.reason]
        if decision.truncated:
            notes.append(f"cut-off in the list, confirmed by the filled-in address: {', '.join(decision.truncated)}")
        return gate(*STAGE, address_checks(app, order), notes=notes)
    cancel(app)
    if decision.action == REVIEW:
        raise ManualReviewRequired(decision.reason)
    assert decision.action == CREATE
    raise NotBuiltYet(f"{decision.reason}; creating the Debtor (task 2.5-2.13) is built in step 8")
