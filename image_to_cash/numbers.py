from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")

_CURRENCY = re.compile(r"\b[A-Z]{3}\b|[€$£¥]")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_amount(text: str) -> Decimal:
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
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        if s.count(decimal_sep) > 1:
            raise ValueError(f"ambiguous number: {text!r}")
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif dots or commas:
        sep = "." if dots else ","
        parts = s.split(sep)
        if len(parts) > 2:
            if not all(len(p) == 3 for p in parts[1:]):
                raise ValueError(f"not a number: {text!r}")
            s = "".join(parts)
        elif len(parts[1]) == 3:
            raise ValueError(f"ambiguous number (thousands or decimals?): {text!r}")
        else:
            s = parts[0] + "." + parts[1]

    try:
        return Decimal(sign + s)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc


def parse_percent(text: str) -> Decimal:
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
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
