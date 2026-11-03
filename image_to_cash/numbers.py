"""
Exact money and percentage handling, shared by extraction and the UI flow.

All amounts are Decimal, never float. Parsing is strict: a value that could be read
two ways (for example "1,234": 1234 or 1.234?) is rejected instead of guessed.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")

# Currency codes and symbols that may surround an amount, e.g. "EUR 570.00" or "40,00 €".
_CURRENCY = re.compile(r"\b[A-Z]{3}\b|[€$£¥]")


def money(value: Decimal) -> Decimal:
    """Round to cents, half up (297.495 -> 297.50)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_amount(text: str) -> Decimal:
    """
    Parse a printed number such as "250.00", "EUR 570.00", "1,234.56", "1.234,56" or "2".

    Raises ValueError when the text is empty, not a number, or ambiguous.
    """
    if text is None:
        raise ValueError("missing number")
    s = _CURRENCY.sub("", str(text)).replace(" ", " ").strip()
    s = s.replace(" ", "").replace("'", "")
    if not s:
        raise ValueError(f"no number in {text!r}")

    sign = ""
    if s[0] in "+-":
        sign, s = ("-" if s[0] == "-" else ""), s[1:]
    if not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        raise ValueError(f"not a number: {text!r}")

    dots, commas = s.count("."), s.count(",")
    if dots and commas:
        # Both present: the right-most one is the decimal separator.
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        if s.count(decimal_sep) > 1:
            raise ValueError(f"ambiguous number: {text!r}")
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif dots or commas:
        sep = "." if dots else ","
        parts = s.split(sep)
        if len(parts) > 2:
            # "1,234,567": only valid as thousands grouping.
            if not all(len(p) == 3 for p in parts[1:]):
                raise ValueError(f"not a number: {text!r}")
            s = "".join(parts)
        elif len(parts[1]) == 3:
            raise ValueError(f"ambiguous number (thousands or decimals?): {text!r}")
        else:
            s = parts[0] + "." + parts[1]

    try:
        return Decimal(sign + s)
    except InvalidOperation as exc:  # pragma: no cover - regexes above make this rare
        raise ValueError(f"not a number: {text!r}") from exc


def parse_percent(text: str) -> Decimal:
    """Parse "10%", "19 %", "7.5%" or "0" into Decimal("10") etc. Negative values are rejected."""
    if text is None:
        raise ValueError("missing percentage")
    s = str(text).strip()
    if s.endswith("%"):
        s = s[:-1]
    value = parse_amount(s)
    if value < 0:
        raise ValueError(f"negative percentage: {text!r}")
    return value


def format_percent(value: Decimal) -> str:
    """Decimal("19") -> "19", Decimal("7.50") -> "7.5" (used in names such as "VAT 19%")."""
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
