from __future__ import annotations

from dataclasses import dataclass

from image_to_cash.extract.crosscheck import fold
from image_to_cash.extract.schema import Address, Debtor, Item
from image_to_cash.ui.grid_ocr import Grid, GridRow, cell_matches

SELECT = "select"
CREATE = "create"
REVIEW = "review"


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    row: GridRow | None = None
    truncated: tuple[str, ...] = ()


def debtor_expected(debtor: Debtor, billing: Address) -> dict[str, str]:
    return {
        "Company": debtor.company or "",
        "First Name": debtor.first_name or "",
        "Name": debtor.last_name or "",
        "ZIP": billing.zip,
        "City": billing.city,
    }


def _differences(row: GridRow, expected: dict[str, str]) -> str:
    diffs = [f"{c} {row.cells.get(c, '')!r} (expected {v!r})" for c, v in expected.items()
             if not cell_matches(row.cells.get(c, ""), v)]
    return ", ".join(diffs)


def decide_debtor(grid: Grid, debtor: Debtor, billing: Address) -> Decision:
    expected = debtor_expected(debtor, billing)
    key = "Company" if debtor.company else "Name"
    exact, related = [], []
    for row in grid.rows:
        how = {c: cell_matches(row.cells.get(c, ""), v) for c, v in expected.items()}
        if all(how.values()):
            exact.append((row, how))
        elif how[key]:
            related.append(row)
    if len(exact) == 1:
        row, how = exact[0]
        truncated = tuple(c for c, h in how.items() if h == "truncated")
        return Decision(SELECT, "one row matches Company, First Name, Name, ZIP and City", row, truncated)
    if len(exact) > 1:
        rows = "; ".join(r.text() for r, _ in exact)
        return Decision(REVIEW, f"{len(exact)} contacts match exactly, cannot choose: {rows}")
    if related:
        diffs = "; ".join(_differences(r, expected) for r in related)
        return Decision(REVIEW, f"no exact contact, but {len(related)} with the same {key} differ: {diffs}")
    return Decision(CREATE, f"no contact matches {debtor.search_text!r}")


def decide_product(grid: Grid, item: Item) -> Decision:
    rows = [r for r in grid.rows if cell_matches(r.cells.get("Item No.", ""), item.sku)]
    if not rows:
        return Decision(CREATE, f"no product with Item No. {item.sku!r}")
    if len(rows) > 1:
        return Decision(REVIEW, f"{len(rows)} products with Item No. {item.sku!r}: " + "; ".join(r.text() for r in rows))
    row = rows[0]
    name = cell_matches(row.cells.get("Name", ""), item.description)
    if not name:
        return Decision(REVIEW, f"Item No. {item.sku!r} exists but its Name {row.cells.get('Name', '')!r} "
                                f"differs from {item.description!r}")
    truncated = tuple(c for c, h in (("Item No.", cell_matches(row.cells.get("Item No.", ""), item.sku)), ("Name", name))
                      if h == "truncated")
    return Decision(SELECT, f"one product with Item No. {item.sku!r}", row, truncated)


def address_parts(address: Address, debtor: Debtor | None = None) -> list[tuple[str, str]]:
    parts = [("name", address.name or (debtor.company if debtor else None) or "")]
    if debtor is not None:
        contact = " ".join(p for p in (debtor.first_name, debtor.last_name) if p)
        if contact:
            parts.append(("contact", contact))
    parts += [("street", address.street), ("ZIP", address.zip), ("City", address.city)]
    return [(label, value) for label, value in parts if value]


def text_contains(text: str, value: str) -> bool:
    return fold(value) in fold(text or "")


def decide_payment(grid: Grid, method: str) -> Decision:
    exact, conflicting = [], []
    for row in grid.rows:
        name = cell_matches(row.cells.get("Name", ""), method)
        description = cell_matches(row.cells.get("Description", ""), method)
        if name and description:
            exact.append(row)
        elif name or description:
            conflicting.append(row)
    if conflicting:
        rows = "; ".join(r.text() for r in conflicting)
        return Decision(REVIEW, f"a terms-of-payment entry conflicts with {method!r}: {rows}")
    if len(exact) > 1:
        return Decision(REVIEW, f"{len(exact)} terms-of-payment entries named {method!r}")
    if exact:
        return Decision(SELECT, f"terms of payment already has {method!r}", exact[0])
    return Decision(CREATE, f"no terms-of-payment entry named {method!r}")
