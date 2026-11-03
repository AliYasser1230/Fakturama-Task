"""
Step C: turn the verbatim Raw extraction into a typed OrderData.

ISO dates, Decimal amounts, percentages as numbers, payment method mapped to the known
list, contact name split into first and last name. Every problem is collected as an
Issue instead of raising on the first one, so a report shows all of them at once.
Anything that would need a guess is an error.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable, TypeVar

from image_to_cash.errors import Issue
from image_to_cash.extract.schema import (
    Address,
    Debtor,
    Item,
    OrderData,
    Payment,
    PaymentMethod,
    RawAddress,
    RawExtraction,
    Totals,
)
from image_to_cash.numbers import parse_amount, parse_percent

T = TypeVar("T")

# Salutations recognized at the start of a contact name ("Ms Marta Klein").
_SALUTATIONS = {"mr": "Mr.", "mrs": "Mrs.", "ms": "Ms.", "herr": "Mr.", "frau": "Mrs."}

_PAYMENT_METHODS = {m.value.casefold(): m for m in PaymentMethod}

_MONTH_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y")


def clean(text: str | None) -> str | None:
    """Trim and collapse whitespace; empty -> None."""
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text or None


def parse_date(text: str) -> date:
    """
    Accept unambiguous formats only: 2026-07-14, 14.07.2026, 14 July 2026, July 14, 2026.
    Slash dates are accepted only when the day is > 12 (otherwise D/M vs M/D is a guess).
    """
    s = clean(text)
    if not s:
        raise ValueError("missing date")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        if a > 12 >= b:
            return date(year, b, a)
        if b > 12 >= a:
            return date(year, a, b)
        raise ValueError(f"ambiguous date (day/month order unknown): {text!r}")
    for fmt in _MONTH_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognized date format: {text!r}")


def parse_payment_method(text: str) -> PaymentMethod:
    s = clean(text)
    if not s:
        raise ValueError("missing payment method")
    try:
        return _PAYMENT_METHODS[s.casefold()]
    except KeyError:
        known = ", ".join(m.value for m in PaymentMethod)
        raise ValueError(f"unknown payment method {text!r} (known: {known})") from None


def split_contact_name(text: str | None) -> tuple[str | None, str | None, str | None]:
    """
    "Marta Klein" -> (None, "Marta", "Klein"); "Ms Marta Klein" -> ("Ms.", "Marta", "Klein").
    One word -> last name only. Three or more words are ambiguous ("Jan van der Berg") and
    raise ValueError, because Debtor matching compares First Name and Name exactly.
    """
    s = clean(text)
    if not s:
        return None, None, None
    parts = s.split(" ")
    salutation = None
    key = parts[0].rstrip(".").casefold()
    if key in _SALUTATIONS and len(parts) > 1:
        salutation = _SALUTATIONS[key]
        parts = parts[1:]
    if len(parts) == 1:
        return salutation, None, parts[0]
    if len(parts) == 2:
        return salutation, parts[0], parts[1]
    raise ValueError(f"cannot split {text!r} into first and last name without guessing")


class _Collector:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, field: str, message: str) -> None:
        self.issues.append(Issue("error", field, message))

    def warn(self, field: str, message: str) -> None:
        self.issues.append(Issue("warning", field, message))

    def parse(self, field: str, fn: Callable[[str], T], value: str | None) -> T | None:
        if clean(value) is None:
            self.error(field, "missing")
            return None
        try:
            return fn(value)  # type: ignore[arg-type]
        except ValueError as exc:
            self.error(field, str(exc))
            return None

    def required(self, field: str, value: str | None) -> str | None:
        value = clean(value)
        if value is None:
            self.error(field, "missing")
        return value

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)


def _address(c: _Collector, prefix: str, raw: RawAddress) -> Address | None:
    fields = {
        "name": clean(raw.name),
        "additional_name": clean(raw.additional_name),
        "street": c.required(f"{prefix}.street", raw.street),
        "address_specification": clean(raw.address_specification),
        "district": clean(raw.district),
        "zip": c.required(f"{prefix}.zip", raw.zip),
        "city": c.required(f"{prefix}.city", raw.city),
        "country": c.required(f"{prefix}.country", raw.country),
    }
    if None in (fields["street"], fields["zip"], fields["city"], fields["country"]):
        return None
    return Address(**fields)


def normalize(raw: RawExtraction) -> tuple[OrderData | None, list[Issue]]:
    """Return (order, issues). order is None when any error was found."""
    c = _Collector()

    for path in raw.unreadable_fields:
        c.error(path, "printed but not clearly legible on the image")

    # Order header
    external_reference = c.required("order.external_reference", raw.order.external_reference)
    order_date = c.parse("order.order_date", parse_date, raw.order.order_date)
    currency = c.required("order.currency", raw.order.currency)
    currency = currency.upper() if currency else None

    # Debtor
    cust = raw.customer
    salutation, first_name, last_name = None, None, None
    try:
        salutation, first_name, last_name = split_contact_name(cust.contact_name)
    except ValueError as exc:
        c.error("customer.contact_name", str(exc))
    if clean(cust.salutation):
        salutation = clean(cust.salutation)
    company = clean(cust.company)
    if not company and not last_name:
        c.error("customer", "neither a company nor a contact name is printed")
    email = clean(cust.email)
    if email and "@" not in email:
        c.warn("customer.email", f"does not look like an e-mail address: {email!r}")
    debtor = Debtor(
        company=company,
        salutation=salutation,
        first_name=first_name,
        last_name=last_name,
        alias=clean(cust.customer_alias),
        email=email,
        phone=clean(cust.phone),
        source_customer_id=clean(raw.order.customer_id),
    )

    # Addresses
    billing = _address(c, "billing_address", raw.billing_address)
    if raw.delivery_address is None:
        delivery = billing
        c.warn("delivery_address", "not printed; the billing address is used for delivery too (spec 2.8)")
    else:
        delivery = _address(c, "delivery_address", raw.delivery_address)

    # Payment
    method = c.parse("payment.method", parse_payment_method, raw.payment.method)
    paid_status = c.required("payment.paid_status", raw.payment.paid_status)
    paid_status = paid_status.upper() if paid_status else None
    payment_date = None
    if clean(raw.payment.payment_date):
        payment_date = c.parse("payment.payment_date", parse_date, raw.payment.payment_date)

    # Items
    items: list[Item] = []
    if not raw.items:
        c.error("items", "no item rows found")
    for i, r in enumerate(raw.items):
        p = f"items[{i}]"
        values = {
            "sku": c.required(f"{p}.sku", r.sku),
            "description": c.required(f"{p}.description", r.description),
            "quantity": c.parse(f"{p}.quantity", parse_amount, r.quantity),
            "unit_net_price": c.parse(f"{p}.unit_net_price", parse_amount, r.unit_net_price),
            "discount_pct": c.parse(f"{p}.discount", parse_percent, r.discount or "0%"),
            "vat_pct": c.parse(f"{p}.vat", parse_percent, r.vat),
            "line_net": c.parse(f"{p}.line_net", parse_amount, r.line_net),
        }
        if clean(r.discount) is None:
            c.warn(f"{p}.discount", "not printed; 0% assumed")
        if None in values.values():
            continue
        position = i + 1
        if clean(r.position):
            try:
                position = int(parse_amount(r.position))
            except ValueError:
                c.warn(f"{p}.position", f"not a number: {r.position!r}; using row order")
        items.append(Item(position=position, unit=clean(r.unit), **values))

    # Totals
    t = raw.totals
    net = c.parse("totals.net_total", parse_amount, t.net_total)
    vat = c.parse("totals.vat_total", parse_amount, t.vat_total)
    gross = c.parse("totals.gross_total", parse_amount, t.gross_total)
    for field, value in (("totals.order_discount", t.order_discount), ("totals.shipping", t.shipping)):
        if clean(value) is None or "free" in value.casefold():
            continue
        try:
            nonzero = parse_amount(value.rstrip("%").strip()) != 0
        except ValueError:
            nonzero = True
        if nonzero:
            # Spec 4.2 keeps discount 0% and free shipping; other values are not automated.
            c.error(field, f"order-level value {value!r} is printed; this flow does not apply it")

    if not c.ok:
        return None, c.issues

    order = OrderData(
        external_reference=external_reference,
        order_date=order_date,
        currency=currency,
        debtor=debtor,
        billing_address=billing,
        delivery_address=delivery,
        payment=Payment(method=method, paid_status=paid_status, payment_date=payment_date),
        items=items,
        totals=Totals(net=net, vat=vat, gross=gross),
    )
    return order, c.issues
