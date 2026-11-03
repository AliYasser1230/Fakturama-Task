import json
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.lines import cell_amount, line_checks
from image_to_cash.ui.grid_ocr import Box, OcrWord, parse_grid, visual_rows

OCR = Path(__file__).parent / "fixtures" / "ocr"
COLUMNS = ("Pos.", "Qty.", "Item No.", "Picture", "Name", "Description", "VAT", "U.Price")


@pytest.fixture
def order(sample_expected_path):
    return OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))


class TableApp:
    def __init__(self, words, cells):
        self.words, self.cells, self.calls = words, cells, []

    @contextmanager
    def revealed(self, screen, control, title=None):
        yield

    def read_table(self, screen, control, title=None, required=None):
        return parse_grid(self.words, COLUMNS, required=required)

    def table_rows(self, screen, control, title=None):
        self.calls.append("table_rows")
        return visual_rows(self.words)

    def read_cell(self, screen, control, row, column, title=None):
        self.calls.append(("read_cell", column))
        return self.cells[(row.cells["Item No."], column)]


def _recorded_items_table():
    data = json.loads((OCR / "items_table.json").read_text(encoding="utf-8"))
    return [OcrWord(w["text"], Box(*w["box"])) for w in data["words"]]


def test_lines_are_checked_even_when_ocr_misses_the_qty_header(order):
    items = [i.model_copy(update={"quantity": Decimal("1")}) for i in order.items]
    app = TableApp(_recorded_items_table(), {("CHR-ERG-OI", "U.Price"): "$250.00", ("MAT-DESK-02", "U.Price"): "$40.00"})
    checks = line_checks(app, "order_editor", items, "order")
    assert all(c.ok for c in checks), [str(c) for c in checks if not c.ok]
    assert [c.what for c in checks] == ["order lines"] + [f"order line {i.sku} {f}" for i in items
                                                           for f in ("Name", "Qty.", "U.Price")]
    assert app.calls.count("table_rows") == 2


def test_a_wrong_quantity_is_reported_with_both_readings(order):
    app = TableApp(_recorded_items_table(), {("CHR-ERG-OI", "U.Price"): "$250.00", ("MAT-DESK-02", "U.Price"): "$40.00"})
    checks = {c.what: c for c in line_checks(app, "order_editor", order.items, "order")}
    assert not checks["order line CHR-ERG-01 Qty."].ok and checks["order line CHR-ERG-01 Qty."].shown == "1.00"
    assert checks["order line CHR-ERG-01 U.Price"].ok and checks["order line CHR-ERG-01 Name"].ok


@pytest.mark.parametrize("shown, value", [("S40.oo", "40.00"), ("S40.00", "40.00"), ("$678.30", "678.30"),
                                          ("$1,250.00", "1250.00"), ("250.0O", "250.00")])
def test_money_cells_accept_the_ocr_lookalikes_of_dollar_and_zero(shown, value):
    assert cell_amount(shown) == Decimal(value)


@pytest.mark.parametrize("shown", ['"78.30', "Total Net", "S4B.00", ""])
def test_money_cells_do_not_guess_other_misreadings(shown):
    assert cell_amount(shown) is None
