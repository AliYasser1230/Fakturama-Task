"""
Step B: every critical value Claude read must also appear in the OCR text of the same
image. A value OCR cannot find may have been invented by the model, so the run stops.

The comparison ignores case and spacing and treats look-alike characters (O/0, I/l/1)
as equal: the goal is to catch invented values, not to punish OCR for misreading a glyph.

Percentages need two extra rules, because Windows OCR is weak on them: it reads "%" as
"96" or "0/0" ("10%" -> "1096" or "100/0"), and it drops small tokens like "0%" at random.
1. A percentage also matches those known misreadings.
2. A discount or VAT rate OCR still cannot find is a warning, not an error, when the
   amounts that determine it were all found by OCR. Step D then proves it:
   - discount: qty x unit net x (1 - discount) must equal the line net;
   - VAT rate: only when every line has the same rate, the VAT total over the line nets
     must equal it. With mixed rates OCR must find every rate.
"""

from __future__ import annotations

from image_to_cash.errors import Issue
from image_to_cash.extract.schema import RawExtraction

_LOOKALIKES = str.maketrans({"o": "0", "i": "1", "l": "1", "|": "1"})

# How Windows OCR has been seen to spell "%" (after fold(), so "o/o" is "0/0").
_PERCENT_MISREADINGS = ("96", "0/0")


def fold(text: str) -> str:
    """Lower-case, drop all whitespace, map look-alike characters."""
    return "".join(text.split()).casefold().translate(_LOOKALIKES)


def spellings(value: str) -> set[str]:
    """The folded value, plus the OCR misreadings of a percent sign if it has one."""
    folded = fold(value)
    if "%" not in folded:
        return {folded}
    return {folded} | {folded.replace("%", alt) for alt in _PERCENT_MISREADINGS}


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


def _determined_by(raw: RawExtraction, path: str) -> tuple[list[str], str] | None:
    """
    For a percentage that step D can prove from other values: the paths of those values
    and a description of the check. None if the value can only be confirmed by OCR.
    """
    if not path.startswith("items[") or not path.endswith((".discount", ".vat")):
        return None
    index = int(path[len("items["):path.index("]")])
    if path.endswith(".discount"):
        p = f"items[{index}]"
        return ([f"{p}.quantity", f"{p}.unit_net_price", f"{p}.line_net"],
                "quantity x unit net x (1 - discount) = line net")
    rates = {fold(item.vat or "") for item in raw.items}
    if len(rates) != 1:
        return None
    return ([f"items[{i}].line_net" for i in range(len(raw.items))] + ["totals.vat_total"],
            "the VAT total over the line nets")


def crosscheck(raw: RawExtraction, ocr_text: str) -> list[Issue]:
    haystack = fold(ocr_text)
    values = critical_values(raw)
    present = {path for path, _ in values}
    missing = {path: value for path, value in values
               if not any(s in haystack for s in spellings(value))}

    issues = []
    for path, value in missing.items():
        proof = _determined_by(raw, path)
        if proof is not None and all(p in present and p not in missing for p in proof[0]):
            issues.append(Issue("warning", path,
                                f"{value!r} was not found in the OCR text; accepted because OCR found "
                                f"the amounts that fix it, and step D checks {proof[1]}"))
        else:
            issues.append(Issue("error", path, f"{value!r} was not found in the OCR text of the image"))
    return issues
