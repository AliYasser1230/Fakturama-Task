import os
import sys
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(
    not (sys.platform == "win32" and os.environ.get("FAKTURAMA_LIVE") == "1"),
    reason="live UI test: needs Windows, a running Fakturama and FAKTURAMA_LIVE=1",
)

seen = {}


@pytest.fixture(scope="module")
def app():
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama

    fakturama = Fakturama.connect(Settings.from_env())
    if fakturama.is_open("order_editor"):
        pytest.skip("a New Order editor is already open in Fakturama; close it first")
    fakturama.bring_to_front()
    fakturama.maximize()
    yield fakturama
    if fakturama.is_open("order_editor"):
        fakturama.close_editor("order_editor")


def test_fill_the_order_header_and_close_without_saving(app):
    from image_to_cash.ui import actions

    actions.click(app.find("main", "new_order"))
    app.wait_open("order_editor")
    seen["number"] = actions.read_value(app.find("order_editor", "number"))
    assert seen["number"]

    assert actions.set_text(app.find("order_editor", "cust_ref"), "LIVE-TEST-0001") == "LIVE-TEST-0001"
    shown = actions.set_date(app.find("order_editor", "date"), date(2026, 7, 14))
    assert actions.parse_display_date(shown) == date(2026, 7, 14)
    assert actions.select_option(app.find("order_editor", "price_mode"), "Net").strip() == "Net"
    assert app.find("order_editor", "subtotal").name == "Total Net"
    assert actions.read_value(app.find("order_editor", "vat_mode")).strip() == "With VAT"
    assert actions.read_value(app.find("order_editor", "number")) == seen["number"]

    actions.click(app.find("order_editor", "select_address"))
    app.wait_open("select_address")
    actions.click(app.find("select_address", "cancel"))
    app.wait_closed("select_address")

    assert app.wait_open("order_editor").name.startswith("*")
    app.close_editor("order_editor")
    assert not app.is_open("order_editor")


def test_the_discarded_order_did_not_use_up_its_number(app):
    from image_to_cash.ui import actions

    if "number" not in seen:
        pytest.skip("the first live test did not run")
    actions.click(app.find("main", "new_order"))
    app.wait_open("order_editor")
    assert actions.read_value(app.find("order_editor", "number")) == seen["number"]
    app.close_editor("order_editor")
    assert not app.is_open("order_editor")
