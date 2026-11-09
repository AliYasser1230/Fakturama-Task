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
    for screen in ("order_editor", "debtor_editor"):
        if fakturama.editor_open(screen):
            pytest.skip(f"{screen} is already open in Fakturama; close it first")
    fakturama.bring_to_front()
    fakturama.maximize()
    yield fakturama
    if fakturama.exists("address_roles", "invoice"):
        fakturama.press("{ESC}")
    for screen in ("debtor_editor", "order_editor"):
        fakturama.close_all(screen)


def test_new_contact_is_filled_in_and_closed_unsaved(app, sample_expected_path):
    from image_to_cash.extract.schema import OrderData
    from image_to_cash.flow.create_debtor import debtor_checks, fill_new_debtor
    from image_to_cash.flow.order import open_order
    from image_to_cash.flow.runner import RunContext

    order = OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))
    ctx = RunContext(order=order, app=app, settings=app.settings)
    assert open_order(ctx).ok

    customer_id = fill_new_debtor(app, order)
    checks = debtor_checks(app, order, customer_id)
    assert all(c.ok for c in checks), [str(c) for c in checks if not c.ok]
    assert app.editor_open("order_editor")

    app.close_editor("debtor_editor")
    app.close_editor("order_editor")
    assert not app.editor_open("debtor_editor") and not app.editor_open("order_editor")
