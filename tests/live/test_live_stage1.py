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
    if fakturama.is_open("order_editor"):
        pytest.skip("a New Order editor is already open in Fakturama; close it first")
    fakturama.bring_to_front()
    fakturama.maximize()
    yield fakturama
    if fakturama.is_open("order_editor"):
        fakturama.close_editor("order_editor")


def test_stage1_opens_the_order_for_the_sample(app, sample_expected_path):
    from image_to_cash.extract.pipeline import load_order_json
    from image_to_cash.flow.order import open_order
    from image_to_cash.flow.runner import RunContext

    order = load_order_json(sample_expected_path, settings=app.settings)
    ctx = RunContext(order=order, app=app, settings=app.settings)
    result = open_order(ctx)
    assert result.ok, [str(c) for c in result.checks]
    assert ctx.order_number
    assert app.read("order_editor", "cust_ref") == order.external_reference
    app.close_editor("order_editor")
    assert not app.is_open("order_editor")
