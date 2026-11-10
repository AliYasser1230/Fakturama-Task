from __future__ import annotations

from datetime import date
from decimal import Decimal

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.flow.lines import cell_amount, checked_cell
from image_to_cash.flow.runner import Check
from image_to_cash.ui.actions import MONTH_ABBR, parse_display_date
from image_to_cash.ui.grid_ocr import GridRow, cell_key, cell_matches, cut_off_stem

DOCS = "documents_list"


def list_date_ok(shown: str, when: date) -> bool:
    if parse_display_date(shown) == when:
        return True
    stem = cut_off_stem(" ".join((shown or "").split()))
    full = f"{MONTH_ABBR[when.month - 1]} {when.day}, {when.year}"
    return stem is not None and "," in stem and cell_key(full).startswith(cell_key(stem))


def document_row(app, document: str, kind: str) -> GridRow:
    app.click("main", "menu_data")
    app.click_when("data_menu", "documents")
    app.wait_open(DOCS)
    app.click_when(DOCS, kind)
    grid = app.search_table(DOCS, document)
    rows = [r for r in (grid.rows if grid else []) if cell_matches(r.cells.get("Document", ""), document)]
    if len(rows) != 1:
        raise ManualReviewRequired(f"Data > Documents shows {len(rows)} rows for {document!r}")
    return rows[0]


def document_checks(app, row: GridRow, *, label: str, document: str, when: date, cust_ref: str, state: str,
                    total: Decimal) -> list[Check]:
    cells = row.cells
    shown_date, date_ok = checked_cell(app, DOCS, "table", row, "Date", lambda s: list_date_ok(s, when))
    shown_total, total_ok = checked_cell(app, DOCS, "table", row, "Total", lambda s: cell_amount(s) == total)
    return [
        Check(f"{label} in Documents: number", document, cells.get("Document", ""),
              cell_matches(cells.get("Document", ""), document) is not None),
        Check(f"{label} in Documents: Date", when.isoformat(), shown_date, date_ok),
        Check(f"{label} in Documents: Cust.Ref.", cust_ref, cells.get("Cust.Ref.", ""),
              cell_matches(cells.get("Cust.Ref.", ""), cust_ref) is not None),
        Check(f"{label} in Documents: State", state, cells.get("State", ""),
              cell_matches(cells.get("State", ""), state) is not None),
        Check(f"{label} in Documents: Total", str(total), shown_total, total_ok),
    ]
