"""
Pydantic models for the extracted order (design doc 3.3 schema).

Two layers:
- Raw*: what Claude reads off the image, every value a verbatim string. This is the
  structured-output schema sent to the API, and what the OCR cross-check compares.
- OrderData: the normalized, typed order the Fakturama flow works with (normalize.py
  turns Raw into OrderData). It also carries the values the spec derives from the
  image, such as the Product gross price (3.9) and the line price (3.16).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from image_to_cash.numbers import format_percent, money

# --------------------------------------------------------------------------------------
# Raw layer: structured output from Claude. Every field is required but nullable, so the
# model has to state "not on the document" explicitly instead of silently skipping it.
# --------------------------------------------------------------------------------------


class _Raw(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawOrderHeader(_Raw):
    external_reference: str | None = Field(description="External / customer reference number.")
    order_date: str | None
    customer_id: str | None
    currency: str | None


class RawCustomer(_Raw):
    company: str | None
    contact_name: str | None = Field(description="Contact person's full name as printed.")
    salutation: str | None = Field(description="Only if printed separately, e.g. 'Mr', 'Ms'.")
    customer_alias: str | None
    email: str | None
    phone: str | None


class RawAddress(_Raw):
    name: str | None = Field(description="First line of the address block (company or recipient).")
    additional_name: str | None = Field(description="Extra name line such as 'c/o ...', if printed.")
    street: str | None = Field(description="Street and house number.")
    address_specification: str | None = Field(description="Extra address line such as floor or building, if printed.")
    district: str | None
    zip: str | None
    city: str | None
    country: str | None


class RawPayment(_Raw):
    method: str | None
    paid_status: str | None
    payment_date: str | None


class RawItem(_Raw):
    position: str | None
    sku: str | None
    description: str | None
    quantity: str | None
    unit: str | None
    unit_net_price: str | None
    discount: str | None
    vat: str | None
    line_net: str | None = Field(description="Printed line total (net).")


class RawTotals(_Raw):
    net_total: str | None
    vat_total: str | None
    gross_total: str | None
    order_discount: str | None = Field(description="Order-level discount, only if printed.")
    shipping: str | None = Field(description="Shipping charge, only if printed.")


class RawExtraction(_Raw):
    order: RawOrderHeader
    customer: RawCustomer
    billing_address: RawAddress
    delivery_address: RawAddress | None = Field(
        description="Null when the document shows no separate delivery address."
    )
    payment: RawPayment
    items: list[RawItem] = Field(description="One entry per printed item row, in printed order.")
    totals: RawTotals
    unreadable_fields: list[str] = Field(
        description="Paths of fields that are printed but not clearly legible, e.g. 'items[0].unit_net_price'."
    )


# --------------------------------------------------------------------------------------
# Normalized layer: what the Fakturama flow uses.
# --------------------------------------------------------------------------------------


class PaymentMethod(str, Enum):
    BANK_TRANSFER = "Bank Transfer"
    CREDIT_CARD = "Credit Card"
    SEPA_DIRECT_DEBIT = "SEPA Direct Debit"

    @property
    def payment_code(self) -> str:
        """Fakturama payment-code dropdown value (spec 2.10.4)."""
        return _PAYMENT_CODES[self]


_PAYMENT_CODES = {
    PaymentMethod.BANK_TRANSFER: "Credit transfer",
    PaymentMethod.CREDIT_CARD: "Credit card",
    PaymentMethod.SEPA_DIRECT_DEBIT: "SEPA direct debit",
}


def _same_text(a: str | None, b: str | None) -> bool:
    return " ".join((a or "").split()).casefold() == " ".join((b or "").split()).casefold()


class Address(BaseModel):
    name: str | None = None
    additional_name: str | None = None
    street: str
    address_specification: str | None = None
    district: str | None = None
    zip: str
    city: str
    country: str

    def same_as(self, other: "Address") -> bool:
        """Same place and recipient, ignoring case and spacing (decides spec 2.8)."""
        return all(_same_text(getattr(self, f), getattr(other, f)) for f in Address.model_fields)


class Debtor(BaseModel):
    company: str | None
    salutation: str | None = None
    first_name: str | None
    last_name: str | None
    alias: str | None = None
    email: str | None = None
    phone: str | None = None
    # Customer ID printed on the image. Kept for the report only: spec 2.6 says to keep
    # the Customer ID that Fakturama proposes.
    source_customer_id: str | None = None

    @property
    def search_text(self) -> str:
        """What to type into "Select the address" (spec 2.2)."""
        return self.company or " ".join(p for p in (self.first_name, self.last_name) if p)


class Payment(BaseModel):
    method: PaymentMethod
    paid_status: str
    payment_date: date | None = None

    @property
    def is_paid(self) -> bool:
        return self.paid_status == "PAID"


class Item(BaseModel):
    position: int
    sku: str
    description: str
    quantity: Decimal
    unit: str | None = None
    unit_net_price: Decimal
    discount_pct: Decimal
    vat_pct: Decimal
    line_net: Decimal  # as printed on the image

    @property
    def vat_name(self) -> str:
        """Name of the Fakturama VAT record, e.g. "VAT 19%" (spec 3.4-3.6)."""
        return f"VAT {format_percent(self.vat_pct)}%"

    @property
    def gross_unit_price(self) -> Decimal:
        """Product master Price (gross): unit net x (1 + VAT/100), no line discount (spec 3.9)."""
        return money(self.unit_net_price * (1 + self.vat_pct / 100))

    @property
    def computed_line_net(self) -> Decimal:
        """qty x unit net x (1 - discount/100) (spec 3.16)."""
        return money(self.quantity * self.unit_net_price * (1 - self.discount_pct / 100))


class Totals(BaseModel):
    net: Decimal
    vat: Decimal
    gross: Decimal


class OrderData(BaseModel):
    external_reference: str
    order_date: date
    currency: str
    debtor: Debtor
    billing_address: Address
    delivery_address: Address
    payment: Payment
    items: list[Item]
    totals: Totals

    @property
    def delivery_same_as_billing(self) -> bool:
        """True: one Debtor address gets both roles; False: a second address is needed (spec 2.8)."""
        return self.billing_address.same_as(self.delivery_address)
