from __future__ import annotations

from decimal import Decimal, InvalidOperation

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import PaymentMethod
from image_to_cash.flow.matching import CREATE, REVIEW, Decision, decide_payment
from image_to_cash.flow.runner import Check, gate
from image_to_cash.ui.actions import same_text

DEBTOR = "debtor_editor"
LIST = "payments_list"
EDITOR = "payment_editor"
STAGE = ("2", "Select or create the Debtor")
ZERO_FIELDS = ("cash_discount", "discount_days", "net_days")
BLANK_TEXTS = ("text_unpaid", "text_deposit", "text_paid")


def is_zero(shown: str) -> bool:
    try:
        return Decimal(shown.replace("%", "").strip() or "x") == 0
    except InvalidOperation:
        return False


def find_in_list(app, method: str) -> Decision:
    app.click("main", "menu_data")
    app.click_when("data_menu", "payments")
    app.wait_open(LIST)
    app.type(LIST, "search", method, commit="")
    return decide_payment(app.read_table_stable(LIST, "table"), method)


def create_payment_method(app, method: PaymentMethod) -> list[Check]:
    name = method.value
    app.click(LIST, "create")
    app.wait_open(EDITOR)
    standard = app.read(EDITOR, "standard")
    app.type(EDITOR, "name", name)
    app.type(EDITOR, "description", name)
    app.choose(EDITOR, "payment_code", method.payment_code)
    for control in ZERO_FIELDS:
        app.type(EDITOR, control, "0", check=is_zero)
    checks = payment_checks(app, method, standard)
    gate(*STAGE, checks)
    saved = app.save(EDITOR, saved_title=name)
    stored = payment_checks(app, method, standard, title=saved)
    return checks + [Check("payment method saved", name, saved, True)] + [
        Check(f"stored {c.what}", c.expected, c.shown, c.ok) for c in stored]


def payment_checks(app, method: PaymentMethod, standard: str, title: str | None = None) -> list[Check]:
    name = method.value
    shown = {c: app.read(EDITOR, c, title=title) for c in (
        "name", "description", "account", "payment_code", "standard", *ZERO_FIELDS, *BLANK_TEXTS)}
    return [
        Check("payment Name", name, shown["name"], same_text(shown["name"], name)),
        Check("payment Description", name, shown["description"], same_text(shown["description"], name)),
        Check("payment Account (blank)", "", shown["account"], shown["account"].strip() == ""),
        Check("payment code", method.payment_code, shown["payment_code"],
              same_text(shown["payment_code"], method.payment_code)),
        *[Check(f"payment {c} (0)", "0", shown[c], is_zero(shown[c])) for c in ZERO_FIELDS],
        *[Check(f"payment {c} (blank)", "", shown[c], shown[c].strip() == "") for c in BLANK_TEXTS],
        Check("standard payment unchanged", standard, shown["standard"], same_text(shown["standard"], standard)),
    ]


def ensure_payment_method(app, method: PaymentMethod) -> list[Check]:
    decision = find_in_list(app, method.value)
    if decision.action == REVIEW:
        raise ManualReviewRequired(decision.reason)
    if decision.action == CREATE:
        return create_payment_method(app, method)
    return [Check("payment method in terms of payment", method.value, decision.row.cells.get("Name", ""), True)]


def select_payment(app, method: PaymentMethod) -> Check:
    name = method.value
    app.select_tab(DEBTOR, "tab_misc")
    hits = [o for o in app.options(DEBTOR, "payment") if same_text(o, name)]
    if len(hits) != 1:
        raise ManualReviewRequired(f"the contact's Payment list offers {len(hits)} entries named {name!r}")
    app.choose(DEBTOR, "payment", name)
    shown = app.read(DEBTOR, "payment")
    return Check("contact Payment", name, shown, same_text(shown, name))
