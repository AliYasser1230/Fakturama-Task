from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired, NotBuiltYet
from image_to_cash.extract.schema import Item
from image_to_cash.flow.matching import CREATE, REVIEW, SELECT, Decision, decide_product
from image_to_cash.flow.runner import Check, RunContext, StageResult
from image_to_cash.ui.grid_ocr import cell_matches

EDITOR = "order_editor"
DIALOG = "select_product"
STAGE = ("3", "Select or create each Product")


def search_product(app, item: Item) -> Decision:
    app.click(EDITOR, "select_product")
    app.wait_open(DIALOG)
    app.type(DIALOG, "search", item.sku, commit="")
    grid = app.read_table_stable(DIALOG, "table")
    return decide_product(grid, item)


def line_check(app, item: Item) -> Check:
    lines = app.read_table(EDITOR, "items")
    found = [r for r in lines.rows if cell_matches(r.cells.get("Item No.", ""), item.sku)]
    shown = ", ".join(r.cells.get("Item No.", "") for r in lines.rows) or "no lines"
    return Check(f"order line for {item.sku}", item.sku, shown, len(found) == 1)


def select_product(app, item: Item) -> Check:
    decision = search_product(app, item)
    if decision.action == SELECT:
        app.click_row(decision.row)
        app.click(DIALOG, "ok")
        app.wait_closed(DIALOG)
        return line_check(app, item)
    app.click(DIALOG, "cancel")
    app.wait_closed(DIALOG)
    if decision.action == REVIEW:
        raise ManualReviewRequired(decision.reason)
    assert decision.action == CREATE
    raise NotBuiltYet(f"{decision.reason}; creating the Product (task 3.4-3.12) is built in step 8")


def add_products(ctx: RunContext) -> StageResult:
    for item in sorted(ctx.order.items, key=lambda i: i.position):
        check = select_product(ctx.app, item)
        if not check.ok:
            raise ManualReviewRequired(f"after selecting {item.sku}: {check}")
        raise NotBuiltYet(f"{item.sku} is on the order; setting Qty., U.Price, VAT and Discount on its line "
                          f"(task 3.13-3.16) is built in step 8")
    raise ManualReviewRequired("the order has no items")
