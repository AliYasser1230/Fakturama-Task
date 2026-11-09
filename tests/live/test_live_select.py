import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not (sys.platform == "win32" and os.environ.get("FAKTURAMA_LIVE") == "1"),
    reason="live UI test: needs Windows, a running Fakturama and FAKTURAMA_LIVE=1",
)

UNKNOWN_COMPANY = "Zz Live Test Unknown GmbH"
UNKNOWN_SKU = "ZZ-LIVE-UNKNOWN-4711"


@pytest.fixture(scope="module")
def app():
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama

    fakturama = Fakturama.connect(Settings.from_env())
    if fakturama.editor_open("order_editor"):
        pytest.skip("a New Order editor is already open in Fakturama; close it first")
    fakturama.bring_to_front()
    fakturama.maximize()
    yield fakturama
    for dialog in ("select_address", "select_product"):
        if fakturama.is_open(dialog):
            fakturama.click(dialog, "cancel")
    fakturama.close_all("order_editor")


def test_unknown_contact_and_product_are_cancelled(app, sample_expected_path):
    from image_to_cash.errors import NotBuiltYet
    from image_to_cash.extract.schema import OrderData
    from image_to_cash.flow.debtor import cancel, search_debtor
    from image_to_cash.flow.matching import CREATE
    from image_to_cash.flow.order import open_order
    from image_to_cash.flow.products import select_product
    from image_to_cash.flow.runner import RunContext

    order = OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))
    order = order.model_copy(update={
        "debtor": order.debtor.model_copy(update={"company": UNKNOWN_COMPANY}),
        "items": [order.items[0].model_copy(update={"sku": UNKNOWN_SKU})],
    })
    ctx = RunContext(order=order, app=app, settings=app.settings)
    assert open_order(ctx).ok

    decision = search_debtor(app, order)
    assert decision.action == CREATE, decision.reason
    cancel(app)
    assert not app.is_open("select_address")
    assert app.read("order_editor", "cust_ref") == order.external_reference

    with pytest.raises(NotBuiltYet, match="no product with Item No."):
        select_product(app, order.items[0])
    assert not app.is_open("select_product")

    app.close_editor("order_editor")
    assert not app.editor_open("order_editor")
