import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not (sys.platform == "win32" and os.environ.get("FAKTURAMA_LIVE") == "1"),
    reason="live UI test: needs Windows, a running Fakturama and FAKTURAMA_LIVE=1",
)


@pytest.fixture(scope="module")
def app():
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama

    fakturama = Fakturama.connect(Settings.from_env())
    if fakturama.editor_open("debtor_editor"):
        pytest.skip("a New Debtor editor is already open in Fakturama; close it first")
    fakturama.bring_to_front()
    fakturama.maximize()
    yield fakturama
    fakturama.close_all("debtor_editor")


def test_existing_bank_transfer_is_found_and_selected_on_a_new_contact(app):
    from image_to_cash.extract.schema import PaymentMethod
    from image_to_cash.flow.matching import CREATE, SELECT
    from image_to_cash.flow.payment_method import find_in_list, select_payment

    decision = find_in_list(app, PaymentMethod.BANK_TRANSFER.value)
    if decision.action == CREATE:
        pytest.skip("Bank Transfer is not in terms of payment yet (a full run creates it); this test never saves")
    assert decision.action == SELECT, decision.reason

    app.click("main", "nav_new_contact")
    app.wait_open("debtor_editor")
    assert select_payment(app, PaymentMethod.BANK_TRANSFER).ok
    app.close_all("debtor_editor")
    assert not app.editor_open("debtor_editor")
