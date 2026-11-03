from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from image_to_cash.numbers import format_percent, money


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


class PaymentMethod(str, Enum):
    BANK_TRANSFER = "Bank Transfer"
    CREDIT_CARD = "Credit Card"
    SEPA_DIRECT_DEBIT = "SEPA Direct Debit"

    @property
    def payment_code(self) -> str:
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
        return all(_same_text(getattr(self, f), getattr(other, f)) for f in Address.model_fields)


class Debtor(BaseModel):
    company: str | None
    salutation: str | None = None
    first_name: str | None
    last_name: str | None
    alias: str | None = None
    email: str | None = None
    phone: str | None = None
    source_customer_id: str | None = None

    @property
    def search_text(self) -> str:
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
    line_net: Decimal

    @property
    def vat_name(self) -> str:
        return f"VAT {format_percent(self.vat_pct)}%"

    @property
    def gross_unit_price(self) -> Decimal:
        return money(self.unit_net_price * (1 + self.vat_pct / 100))

    @property
    def computed_line_net(self) -> Decimal:
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
        return self.billing_address.same_as(self.delivery_address)
