from __future__ import annotations

from decimal import Decimal

from image_to_cash.errors import ManualReviewRequired
from image_to_cash.flow.matching import CREATE, REVIEW, Decision, decide_vat, percent_matches
from image_to_cash.flow.runner import Check, gate
from image_to_cash.numbers import format_percent
from image_to_cash.ui.actions import same_text

LIST = "vats_list"
EDITOR = "vat_editor"
STAGE = ("3", "Select or create each Product")
STANDARD_CODE = "S (Standard rate)"


def vat_name(percent: Decimal) -> str:
    return f"VAT {format_percent(percent)}%"


def find_vat(app, name: str, percent: str) -> Decision:
    app.click("main", "menu_data")
    app.click_when("data_menu", "vats")
    app.wait_open(LIST)
    app.type(LIST, "search", name, commit="")
    return decide_vat(app.read_table_stable(LIST, "table"), name, percent)


def vat_checks(app, name: str, percent: str, standard: str, title: str | None = None) -> list[Check]:
    shown = {c: app.read(EDITOR, c, title=title) for c in ("name", "description", "vat_code", "value", "standard")}
    return [
        Check("VAT Name", name, shown["name"], same_text(shown["name"], name)),
        Check("VAT Description", name, shown["description"], same_text(shown["description"], name)),
        Check("VAT code (E-Invoice)", STANDARD_CODE, shown["vat_code"], same_text(shown["vat_code"], STANDARD_CODE)),
        Check("VAT Value", f"{percent}%", shown["value"], percent_matches(shown["value"], percent)),
        Check("standard VAT unchanged", standard, shown["standard"], same_text(shown["standard"], standard)),
    ]


def check_existing_vat(app, decision: Decision, name: str) -> list[Check]:
    app.click_row(decision.row, double=True)
    app.wait_open(EDITOR, title=name)
    code = app.read(EDITOR, "vat_code", title=name)
    app.close_editor(EDITOR, title=name)
    if not same_text(code, STANDARD_CODE):
        raise ManualReviewRequired(f"VAT {name!r} exists but its VAT code is {code!r}, not {STANDARD_CODE!r}")
    return [Check(f"existing {name} VAT code", STANDARD_CODE, code, True)]


def create_vat(app, name: str, percent: str) -> list[Check]:
    app.click(LIST, "create")
    app.wait_open(EDITOR)
    standard = app.read(EDITOR, "standard")
    app.type(EDITOR, "name", name)
    app.type(EDITOR, "description", name)
    if not same_text(app.read(EDITOR, "vat_code"), STANDARD_CODE):
        app.choose(EDITOR, "vat_code", STANDARD_CODE)
    app.type(EDITOR, "value", percent, check=lambda shown: percent_matches(shown, percent))
    checks = vat_checks(app, name, percent, standard)
    gate(*STAGE, checks)
    saved = app.save(EDITOR, saved_title=name)
    stored = vat_checks(app, name, percent, standard, title=saved)
    return checks + [Check("VAT saved", name, saved, True)] + [
        Check(f"stored {c.what}", c.expected, c.shown, c.ok) for c in stored]


def ensure_vat(app, percent: Decimal) -> list[Check]:
    name, value = vat_name(percent), format_percent(percent)
    decision = find_vat(app, name, value)
    if decision.action == REVIEW:
        raise ManualReviewRequired(decision.reason)
    if decision.action == CREATE:
        return create_vat(app, name, value)
    return [Check(f"{name} in VATs", f"{value}%", decision.row.cells.get("Value", ""), True)] + \
        check_existing_vat(app, decision, name)
