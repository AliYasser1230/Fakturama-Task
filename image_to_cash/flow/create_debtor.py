from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired, VerificationFailed
from image_to_cash.extract.schema import Address, Debtor, OrderData
from image_to_cash.flow.runner import Check
from image_to_cash.numbers import parse_percent
from image_to_cash.ui.actions import same_text

EDITOR = "debtor_editor"
ROLES = "address_roles"
NO_SALUTATION = "---"
SALUTATIONS = {"mr": "Mr", "herr": "Mr", "mrs": "Ms", "ms": "Ms", "frau": "Ms"}
INVOICE_ROLE = "Invoice address"
DELIVERY_ROLE = "Delivery address"


def salutation_option(salutation: str | None) -> str:
    if not salutation:
        return NO_SALUTATION
    option = SALUTATIONS.get(salutation.strip().rstrip(".").casefold())
    if option is None:
        raise ManualReviewRequired(f"no Fakturama salutation for {salutation!r}")
    return option


def additional_name(address: Address, debtor: Debtor) -> str | None:
    if address.additional_name:
        return address.additional_name
    if address.name and not same_text(address.name, debtor.company or ""):
        return address.name
    return None


def address_fields(address: Address, debtor: Debtor, *, main: bool) -> dict[str, str]:
    fields = {
        "additional_name": additional_name(address, debtor),
        "street": address.street,
        "address_specification": address.address_specification,
        "district": address.district,
        "zip": address.zip,
        "city": address.city,
    }
    if main:
        fields["email"] = debtor.email
        fields["phone"] = debtor.phone
    return {k: v for k, v in fields.items() if v}


def roles_for(order: OrderData) -> list[tuple[str, tuple[str, ...]]]:
    if order.delivery_same_as_billing:
        return [("main", (INVOICE_ROLE, DELIVERY_ROLE))]
    return [("main", (INVOICE_ROLE,)), ("additional", (DELIVERY_ROLE,))]


def open_new_debtor(app) -> str:
    if app.editor_open(EDITOR):
        raise ManualReviewRequired("a New Debtor editor is already open in Fakturama; save or close it, then run again")
    app.click("main", "nav_new_contact")
    app.wait_open(EDITOR)
    customer_id = app.read(EDITOR, "customer_id")
    if not customer_id.strip():
        raise VerificationFailed("the New Debtor has no proposed Customer ID")
    return customer_id


def set_roles(app, roles: tuple[str, ...]) -> None:
    app.click(EDITOR, "address_type_menu")
    for role in (INVOICE_ROLE, DELIVERY_ROLE):
        control = "invoice" if role == INVOICE_ROLE else "delivery"
        app.wait_for(ROLES, control)
        app.tick(ROLES, control, role in roles)
    app.press("{ESC}")
    app.wait_gone(ROLES, "invoice")


def fill_address(app, address: Address, debtor: Debtor, roles: tuple[str, ...], *, main: bool) -> None:
    for control, value in address_fields(address, debtor, main=main).items():
        app.type(EDITOR, control, value)
    app.choose(EDITOR, "country", address.country)
    set_roles(app, roles)


def fill_new_debtor(app, order: OrderData) -> str:
    debtor = order.debtor
    customer_id = open_new_debtor(app)
    if debtor.company:
        app.type(EDITOR, "company", debtor.company, commit="")
    salutation = salutation_option(debtor.salutation)
    if not same_text(app.read(EDITOR, "salutation"), salutation):
        app.choose(EDITOR, "salutation", salutation)
    if debtor.first_name:
        app.type(EDITOR, "first_name", debtor.first_name)
    if debtor.last_name:
        app.type(EDITOR, "last_name", debtor.last_name)

    app.select_tab(EDITOR, "tab_addresses")
    for which, roles in roles_for(order):
        if which == "main":
            app.select_tab(EDITOR, "tab_main_address")
            fill_address(app, order.billing_address, debtor, roles, main=True)
        else:
            app.click(EDITOR, "add_address")
            app.wait_for(EDITOR, "tab_additional_address")
            app.select_tab(EDITOR, "tab_additional_address")
            fill_address(app, order.delivery_address, debtor, roles, main=False)

    app.select_tab(EDITOR, "tab_misc")
    if debtor.alias:
        app.type(EDITOR, "alias", debtor.alias)
    app.type(EDITOR, "discount", "0", check=lambda shown: _is_zero_percent(shown))
    app.choose(EDITOR, "net_or_gross", "Net")
    return customer_id


def _is_zero_percent(shown: str) -> bool:
    try:
        return parse_percent(shown) == 0
    except ValueError:
        return False


def _check(what: str, expected: str, shown: str) -> Check:
    return Check(what, expected, shown, same_text(shown, expected))


def debtor_checks(app, order: OrderData, customer_id: str) -> list[Check]:
    debtor = order.debtor
    checks = [_check("Customer ID (proposed, unchanged)", customer_id, app.read(EDITOR, "customer_id"))]
    if debtor.company:
        checks.append(_check("Company", debtor.company, app.read(EDITOR, "company")))
    checks.append(_check("Salutation", salutation_option(debtor.salutation), app.read(EDITOR, "salutation")))
    checks.append(_check("First Name", debtor.first_name or "", app.read(EDITOR, "first_name")))
    checks.append(_check("Last Name", debtor.last_name or "", app.read(EDITOR, "last_name")))

    app.select_tab(EDITOR, "tab_addresses")
    for which, roles in roles_for(order):
        tab = "tab_main_address" if which == "main" else "tab_additional_address"
        address = order.billing_address if which == "main" else order.delivery_address
        label = "Main address" if which == "main" else "additional address"
        app.select_tab(EDITOR, tab)
        for control, value in address_fields(address, debtor, main=which == "main").items():
            checks.append(_check(f"{label} {control}", value, app.read(EDITOR, control)))
        checks.append(_check(f"{label} country", address.country, app.read(EDITOR, "country")))
        shown_roles = app.read(EDITOR, "address_type")
        checks.append(Check(f"{label} role", " + ".join(roles), shown_roles,
                            all(r in shown_roles for r in roles) and
                            not any(r in shown_roles for r in (INVOICE_ROLE, DELIVERY_ROLE) if r not in roles)))

    app.select_tab(EDITOR, "tab_misc")
    if debtor.alias:
        checks.append(_check("Alias name", debtor.alias, app.read(EDITOR, "alias")))
    discount = app.read(EDITOR, "discount")
    checks.append(Check("Discount", "0%", discount, _is_zero_percent(discount)))
    checks.append(_check("Net or Gross", "Net", app.read(EDITOR, "net_or_gross")))
    return checks
