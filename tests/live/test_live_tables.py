import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not (sys.platform == "win32" and os.environ.get("FAKTURAMA_LIVE") == "1"),
    reason="live UI test: needs Windows, a running Fakturama and FAKTURAMA_LIVE=1",
)

VAT_COLUMNS = ["Standard", "Name", "Description", "Value"]
DOCUMENT_COLUMNS = ["Document", "Date", "Name", "Cust.Ref.", "State", "Total", "Printed"]
ADDRESS_COLUMNS = ["No.", "First Name", "Name", "Company", "ZIP", "City"]


@pytest.fixture(scope="module")
def app():
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama

    fakturama = Fakturama.connect(Settings.from_env())
    for screen in ("order_editor", "vat_editor"):
        if fakturama.is_open(screen):
            pytest.skip(f"{screen} is already open in Fakturama; close it first")
    fakturama.bring_to_front()
    fakturama.maximize()
    yield fakturama
    if fakturama.is_open("select_address"):
        from image_to_cash.ui import actions
        actions.click(fakturama.find("select_address", "cancel"))
    if fakturama.is_open("order_editor"):
        fakturama.close_editor("order_editor")
    if fakturama.is_open("vat_editor", title="Tax-free"):
        fakturama.close_editor("vat_editor", title="Tax-free")


def _open_from_data_menu(app, item, screen):
    from image_to_cash.ui import actions

    actions.click(app.find("main", "menu_data"))
    app.wait_open("data_menu")
    actions.click(app.find("data_menu", item))
    app.wait_open(screen)


def test_vat_list_row_is_read_selected_and_opened(app):
    from image_to_cash.ui import actions
    from image_to_cash.ui.grid_ocr import click_row, find_rows, read_grid

    _open_from_data_menu(app, "vats", "vats_list")
    grid = read_grid(app.find("vats_list", "table"), VAT_COLUMNS)
    hits = find_rows(grid, {"Name": "Tax-free"})
    assert len(hits) == 1
    row, _ = hits[0]
    assert row.cells["Description"] == "Free of Tax"

    click_row(row, double=True)
    app.wait_open("vat_editor", title="Tax-free")
    assert actions.read_value(app.find("vat_editor", "name", title="Tax-free")) == "Tax-free"
    assert actions.read_value(app.find("vat_editor", "vat_code", title="Tax-free")).startswith("S (Standard rate)")
    assert actions.read_value(app.find("vat_editor", "value", title="Tax-free")) == "0%"
    app.close_editor("vat_editor", title="Tax-free")
    assert not app.is_open("vat_editor", title="Tax-free")

    again = read_grid(app.find("vats_list", "table"), VAT_COLUMNS)
    assert [r.cells["Name"] for r in again.rows] == [r.cells["Name"] for r in grid.rows]


def test_documents_list_header_is_read(app):
    from image_to_cash.ui.grid_ocr import read_grid

    _open_from_data_menu(app, "documents", "documents_list")
    grid = read_grid(app.find("documents_list", "table"), DOCUMENT_COLUMNS)
    assert grid.columns == tuple(DOCUMENT_COLUMNS)


def test_address_selector_table_is_read_and_cancelled(app):
    from image_to_cash.ui import actions
    from image_to_cash.ui.grid_ocr import read_grid
    from image_to_cash.ui.waits import wait_stable

    actions.click(app.find("main", "new_order"))
    app.wait_open("order_editor")
    actions.click(app.find("order_editor", "select_address"))
    app.wait_open("select_address")
    grid = wait_stable(lambda: read_grid(app.find("select_address", "table"), ADDRESS_COLUMNS).signature(),
                       timeout=10, what="the address list")
    assert isinstance(grid, tuple)
    header = read_grid(app.find("select_address", "table"), ADDRESS_COLUMNS)
    assert header.columns == tuple(ADDRESS_COLUMNS)
    actions.click(app.find("select_address", "cancel"))
    app.wait_closed("select_address")
    app.close_editor("order_editor")
    assert not app.is_open("order_editor")
