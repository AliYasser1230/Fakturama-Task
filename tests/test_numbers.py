from decimal import Decimal

import pytest

from image_to_cash.numbers import format_percent, money, parse_amount, parse_percent


@pytest.mark.parametrize(
    "text, expected",
    [
        ("250.00", "250.00"),
        ("EUR 570.00", "570.00"),
        ("40,00 €", "40.00"),
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234,567", "1234567"),
        ("2", "2"),
        ("1.5", "1.5"),
        ("-3.10", "-3.10"),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "1,234", "1.234", "12a", "EUR", None])
def test_parse_amount_rejects_bad_or_ambiguous(text):
    with pytest.raises(ValueError):
        parse_amount(text)


@pytest.mark.parametrize("text, expected", [("10%", "10"), ("19 %", "19"), ("0%", "0"), ("7.5%", "7.5"), ("16", "16")])
def test_parse_percent(text, expected):
    assert parse_percent(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["-5%", "abc%", ""])
def test_parse_percent_rejects(text):
    with pytest.raises(ValueError):
        parse_percent(text)


def test_money_rounds_half_up():
    assert money(Decimal("297.495")) == Decimal("297.50")
    assert money(Decimal("0.005")) == Decimal("0.01")
    assert str(money(Decimal("450"))) == "450.00"


@pytest.mark.parametrize("value, expected", [("19", "19"), ("19.00", "19"), ("7.50", "7.5"), ("0", "0")])
def test_format_percent(value, expected):
    assert format_percent(Decimal(value)) == expected
