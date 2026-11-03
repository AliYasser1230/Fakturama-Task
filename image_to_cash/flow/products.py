from __future__ import annotations

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import Item
from image_to_cash.flow.create_product import create_product
from image_to_cash.flow.lines import complete_line
from image_to_cash.flow.matching import CREATE, REVIEW, SELECT, Decision, decide_product
from image_to_cash.flow.runner import Check, RunContext, StageResult, gate
from image_to_cash.flow.vat import ensure_vat
from image_to_cash.ui.grid_ocr import cell_matches

EDITOR = "order_editor"
DIALOG = "select_product"
STAGE = ("3", "Select or create each Product")


AUTO_SELECTED = "Fakturama selected the only product matching the SKU itself"


def search_product(app, item: Item) -> Decision:
    app.click(EDITOR, "select_product")
    app.wait_open(DIALOG)
    grid = app.search_table(DIALOG, item.sku)
    if grid is None:
        return Decision(SELECT, AUTO_SELECTED)
    return decide_product(grid, item)


def line_check(app, item: Item) -> Check:
    lines = app.read_table(EDITOR, "items", required=("Item No.",))
    found = [r for r in lines.rows if cell_matches(r.cells.get("Item No.", ""), item.sku)]
    shown = ", ".join(r.cells.get("Item No.", "") for r in lines.rows) or "no lines"
    return Check(f"order line for {item.sku}", item.sku, shown, len(found) == 1)


def choose_row(app, decision: Decision) -> None:
    if decision.row is None:
        return
    app.click_row(decision.row)
    app.click(DIALOG, "ok")
    app.wait_closed(DIALOG)


def cancel(app) -> None:
    app.click(DIALOG, "cancel")
    app.wait_closed(DIALOG)


def select_product(app, item: Item) -> list[Check]:
    decision = search_product(app, item)
    if decision.action == SELECT:
        choose_row(app, decision)
        return [line_check(app, item)]
    cancel(app)
    if decision.action == REVIEW:
        raise ManualReviewRequired(decision.reason)
    assert decision.action == CREATE
    created = ensure_vat(app, item.vat_pct) + create_product(app, item)
    app.activate(EDITOR)
    again = search_product(app, item)
    if again.action != SELECT:
        cancel(app)
        raise ManualReviewRequired(f"product {item.sku} was saved, but Select a product does not show it as the one "
                                   f"exact match: {again.reason}")
    choose_row(app, again)
    shown = again.row.cells.get("Item No.", "") if again.row is not None else AUTO_SELECTED
    return created + [Check(f"new product {item.sku} selected in the order", item.sku, shown, True),
                      line_check(app, item)]


def add_products(ctx: RunContext) -> StageResult:
    checks: list[Check] = []
    done: list[Item] = []
    items = sorted(ctx.order.items, key=lambda i: i.position)
    if not items:
        raise ManualReviewRequired("the order has no items")
    for item in items:
        added = select_product(ctx.app, item)
        if not added[-1].ok:
            raise ManualReviewRequired(f"after selecting {item.sku}: {added[-1]}")
        line = complete_line(ctx.app, item, done)
        checks += added + line
        gate(*STAGE, checks)
        done.append(item)
    return gate(*STAGE, checks, notes=[f"{len(done)} line(s) completed in source order"])
