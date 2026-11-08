from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.create_debtor import debtor_checks, fill_new_debtor
from image_to_cash.flow.matching import CREATE, REVIEW, SELECT, Decision, address_parts, decide_debtor, text_contains
from image_to_cash.flow.payment_method import ensure_payment_method, select_payment
from image_to_cash.flow.runner import Check, RunContext, StageResult, gate
from image_to_cash.ui.grid_ocr import cell_matches

EDITOR = "order_editor"
DEBTOR = "debtor_editor"
DIALOG = "select_address"
STAGE = ("2", "Select or create the Debtor")


AUTO_SELECTED = "Fakturama selected the only contact matching the search itself"


def search_debtor(app, order: OrderData) -> Decision:
    app.click(EDITOR, "select_address")
    app.wait_open(DIALOG)
    grid = app.search_table(DIALOG, order.debtor.search_text)
    if grid is None:
        return Decision(SELECT, AUTO_SELECTED)
    return decide_debtor(grid, order.debtor, order.billing_address)


def choose_row(app, decision: Decision) -> None:
    if decision.row is None:
        return
    app.click_row(decision.row)
    app.click(DIALOG, "ok")
    app.wait_closed(DIALOG)


def cancel(app) -> None:
    app.click(DIALOG, "cancel")
    app.wait_closed(DIALOG)


def address_checks(app, order: OrderData, screen: str = EDITOR, title: str | None = None) -> list[Check]:
    checks = []
    if app.exists(screen, "tab_invoice_address", title):
        app.click(screen, "tab_invoice_address", title)
    invoice = app.read(screen, "address", title)
    for label, value in address_parts(order.billing_address, order.debtor):
        checks.append(Check(f"Invoice address {label}", value, " / ".join(invoice.splitlines()),
                            text_contains(invoice, value)))

    if app.exists(screen, "tab_delivery_address", title):
        app.click(screen, "tab_delivery_address", title)
        delivery = app.read(screen, "delivery_address", title)
        shown = " / ".join(delivery.splitlines())
        company = order.debtor.company or ""
        for label, value in address_parts(order.delivery_address):
            if label == "name" and company and not text_contains(delivery, value):
                checks.append(Check("Delivery address name (Fakturama prints the company)", f"{value} or {company}",
                                    shown, text_contains(delivery, company)))
                continue
            checks.append(Check(f"Delivery address {label}", value, shown, text_contains(delivery, value)))
        app.click(screen, "tab_invoice_address", title)
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
    payment = ensure_payment_method(app, order.payment.method)
    customer_id = fill_new_debtor(app, order)
    filled = debtor_checks(app, order, customer_id) + [select_payment(app, order.payment.method)]
    gate(*STAGE, payment + filled)

    saved = app.save(DEBTOR, saved_title=None)
    app.activate(EDITOR)
    again = search_debtor(app, order)
    if again.action != SELECT:
        cancel(app)
        raise ManualReviewRequired(f"the new contact {customer_id} was saved as {saved!r}, but Select the address "
                                   f"does not show it as the one exact match: {again.reason}")
    choose_row(app, again)
    shown_id = again.row.cells.get("No.", "") if again.row is not None else AUTO_SELECTED
    reselected = [Check("new contact saved", customer_id, saved, True),
                  Check("new contact reselected in the order", customer_id, shown_id,
                        again.row is None or cell_matches(shown_id, customer_id) is not None)]
    return gate(*STAGE, payment + filled + reselected + address_checks(app, order), notes=[
        decision.reason, f"created contact {customer_id} (saved as {saved!r}) and selected it in the order",
        "payment method resolved before New Contact: Fakturama 2.2.0 fills the contact's Payment "
        "list when the contact editor opens"])
