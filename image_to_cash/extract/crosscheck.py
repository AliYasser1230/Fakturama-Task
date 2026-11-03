"""
Step B: every critical value Claude read must also appear in the OCR text of the same
image. A value OCR cannot find may have been invented by the model, so the run stops.

The comparison ignores case and spacing and treats look-alike characters (O/0, I/l/1)
as equal: the goal is to catch invented values, not to punish OCR for misreading a glyph.
"""

from __future__ import annotations

from image_to_cash.errors import Issue
from image_to_cash.extract.schema import RawExtraction

_LOOKALIKES = str.maketrans({"o": "0", "i": "1", "l": "1", "|": "1"})


def fold(text: str) -> str:
    """Lower-case, drop all whitespace, map look-alike characters."""
    return "".join(text.split()).casefold().translate(_LOOKALIKES)


def critical_values(raw: RawExtraction) -> list[tuple[str, str]]:
    """(field path, value) pairs that a wrong reading would turn into wrong records."""
    values: list[tuple[str | None, str]] = [
        (raw.order.external_reference, "order.external_reference"),
        (raw.order.order_date, "order.order_date"),
        (raw.customer.company, "customer.company"),
        (raw.customer.contact_name, "customer.contact_name"),
        (raw.customer.customer_alias, "customer.customer_alias"),
        (raw.customer.email, "customer.email"),
        (raw.customer.phone, "customer.phone"),
        (raw.billing_address.street, "billing_address.street"),
        (raw.billing_address.zip, "billing_address.zip"),
        (raw.billing_address.city, "billing_address.city"),
        (raw.payment.method, "payment.method"),
        (raw.payment.paid_status, "payment.paid_status"),
        (raw.payment.payment_date, "payment.payment_date"),
        (raw.totals.net_total, "totals.net_total"),
        (raw.totals.vat_total, "totals.vat_total"),
        (raw.totals.gross_total, "totals.gross_total"),
    ]
    if raw.delivery_address is not None:
        values += [
            (raw.delivery_address.name, "delivery_address.name"),
            (raw.delivery_address.street, "delivery_address.street"),
            (raw.delivery_address.zip, "delivery_address.zip"),
            (raw.delivery_address.city, "delivery_address.city"),
        ]
    for i, item in enumerate(raw.items):
        p = f"items[{i}]"
        values += [
            (item.sku, f"{p}.sku"),
            (item.description, f"{p}.description"),
            (item.quantity, f"{p}.quantity"),
            (item.unit_net_price, f"{p}.unit_net_price"),
            (item.discount, f"{p}.discount"),
            (item.vat, f"{p}.vat"),
            (item.line_net, f"{p}.line_net"),
        ]
    return [(path, value) for value, path in values if value and value.strip()]


def crosscheck(raw: RawExtraction, ocr_text: str) -> list[Issue]:
    haystack = fold(ocr_text)
    return [
        Issue("error", path, f"{value!r} was not found in the OCR text of the image")
        for path, value in critical_values(raw)
        if fold(value) not in haystack
    ]
