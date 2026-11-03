import pytest

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import Address, Debtor, OrderData
from image_to_cash.flow.create_debtor import (
    additional_name,
    address_fields,
    debtor_checks,
    fill_new_debtor,
    roles_for,
    salutation_option,
)
from image_to_cash.flow.runner import GateFailed, gate
from tests.fakes import FakeApp


@pytest.fixture
def order(sample_expected_path):
    return OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))


def _value(app, key):
    return app.values[("debtor_editor", key)]


def test_new_contact_gets_main_and_delivery_addresses_with_their_roles(order):
    app = FakeApp()
    customer_id = fill_new_debtor(app, order)
    assert customer_id == "CUST000001"
    assert _value(app, "company") == "Northstar Office GmbH"
    assert (_value(app, "first_name"), _value(app, "last_name")) == ("Marta", "Klein")
    assert _value(app, "salutation") == "---"
    assert _value(app, "main.street") == "Friedrichstrasse 88"
    assert (_value(app, "main.zip"), _value(app, "main.city"), _value(app, "main.country")) == ("10117", "Berlin", "Germany")
    assert _value(app, "main.email") == "marta.klein@example.test"
    assert _value(app, "main.phone") == "+49 30 5550 1420"
    assert _value(app, "main.additional_name") == ""
    assert _value(app, "main.address_type") == "Invoice address"
    assert _value(app, "additional.street") == "Beusselstrasse 44"
    assert _value(app, "additional.additional_name") == "Northstar Office Warehouse"
    assert _value(app, "additional.zip") == "10553"
    assert _value(app, "additional.email") == ""
    assert _value(app, "additional.address_type") == "Delivery address"
    assert _value(app, "alias") == "NORTHSTAR-BERLIN"
    assert _value(app, "discount") == "0%"
    assert _value(app, "net_or_gross") == "Net"
    assert ("click", "debtor_editor", "add_address") in app.calls

    checks = debtor_checks(app, order, customer_id)
    assert all(c.ok for c in checks), [str(c) for c in checks if not c.ok]
    assert {"Main address role", "additional address role", "Alias name", "Net or Gross"} <= {c.what for c in checks}


def test_same_billing_and_delivery_means_one_address_with_both_roles(order):
    same = order.model_copy(update={"delivery_address": order.billing_address})
    app = FakeApp()
    fill_new_debtor(app, same)
    assert ("click", "debtor_editor", "add_address") not in app.calls
    assert _value(app, "main.address_type") == "Invoice address, Delivery address"
    assert all(c.ok for c in debtor_checks(app, same, "CUST000001"))


def test_final_check_catches_a_value_fakturama_changed(order):
    def reformat_phone(app):
        app.values[("debtor_editor", "main.phone")] = "+49305550"

    app = FakeApp(after={("type", "debtor_editor", "phone"): reformat_phone})
    customer_id = fill_new_debtor(app, order)
    with pytest.raises(GateFailed) as exc:
        gate("2", "Select or create the Debtor", debtor_checks(app, order, customer_id))
    assert [c.what for c in exc.value.result.checks if not c.ok] == ["Main address phone"]


def test_an_open_new_debtor_editor_stops_the_run(order):
    app = FakeApp(open_screens={"debtor_editor"})
    with pytest.raises(ManualReviewRequired, match="already open"):
        fill_new_debtor(app, order)


@pytest.mark.parametrize("given, option", [(None, "---"), ("", "---"), ("Mr", "Mr"), ("Herr", "Mr"),
                                           ("Mrs.", "Ms"), ("Frau", "Ms")])
def test_salutation_option(given, option):
    assert salutation_option(given) == option


def test_unknown_salutation_needs_review():
    with pytest.raises(ManualReviewRequired):
        salutation_option("Dr")


def test_additional_name_only_when_the_source_supplies_one():
    debtor = Debtor(company="Northstar Office GmbH", first_name="Marta", last_name="Klein", email="m@example.test")
    billing = Address(name="Northstar Office GmbH", street="A 1", zip="1", city="B", country="Germany")
    warehouse = billing.model_copy(update={"name": "Northstar Office Warehouse"})
    explicit = billing.model_copy(update={"additional_name": "c/o Reception"})
    assert additional_name(billing, debtor) is None
    assert additional_name(warehouse, debtor) == "Northstar Office Warehouse"
    assert additional_name(explicit, debtor) == "c/o Reception"
    assert "email" in address_fields(billing, debtor, main=True)
    assert "email" not in address_fields(billing, debtor, main=False)


def test_roles_for(order):
    assert roles_for(order) == [("main", ("Invoice address",)), ("additional", ("Delivery address",))]
    same = order.model_copy(update={"delivery_address": order.billing_address})
    assert roles_for(same) == [("main", ("Invoice address", "Delivery address"))]


def test_fakturamas_duplicate_contact_message_stops_before_saving(order):
    app = FakeApp(after={("dialog", "entering the contact's street"): (
        "Duplicate Contact", "There is already a contact with the same name and street: Marta Klein; Friedrichstrasse 88")})
    with pytest.raises(ManualReviewRequired, match="Duplicate Contact.*Friedrichstrasse 88"):
        fill_new_debtor(app, order)
    assert app.saved == []
