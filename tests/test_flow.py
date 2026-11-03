import sys
from datetime import date

import pytest

import main
from image_to_cash.errors import ManualReviewRequired
from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.order import open_order
from image_to_cash.flow.runner import GateFailed, RunContext, Stage, format_run, run_flow
from image_to_cash.flow.stages import STAGES
from image_to_cash.settings import Settings
from tests.fakes import ADDRESS_COLUMNS, FakeApp, grid

@pytest.fixture
def order(sample_expected_path):
    return OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))


def _ctx(order, app):
    return RunContext(order=order, app=app, settings=Settings())


def test_stage1_fills_the_header_in_the_tasks_order(order):
    app = FakeApp()
    ctx = _ctx(order, app)
    result = open_order(ctx)
    assert app.calls == [
        ("click", "main", "new_order"),
        ("set_date", "order_editor", "date", date(2026, 7, 14)),
        ("type", "order_editor", "cust_ref", "WEB-2026-0714-A17"),
        ("choose", "order_editor", "price_mode", "Net"),
    ]
    assert result.ok and len(result.checks) == 6
    assert ctx.order_number == "PO000001"
    assert app.values[("order_editor", "number")] == "PO000001"


def test_stage1_sets_with_vat_only_when_it_is_not_set(order):
    app = FakeApp(new_order={"vat_mode": "Without VAT"})
    open_order(_ctx(order, app))
    assert ("choose", "order_editor", "vat_mode", "With VAT") in app.calls


def test_stage1_refuses_when_an_order_is_already_open(order):
    app = FakeApp(open_screens={"order_editor"})
    with pytest.raises(ManualReviewRequired, match="already open"):
        open_order(_ctx(order, app))
    assert app.calls == []


def test_final_check_catches_a_field_that_changed_afterwards(order):
    def clear_reference(app):
        app.values[("order_editor", "cust_ref")] = ""

    app = FakeApp(after={("choose", "order_editor", "price_mode"): clear_reference})
    with pytest.raises(GateFailed) as exc:
        open_order(_ctx(order, app))
    failed = [c.what for c in exc.value.result.checks if not c.ok]
    assert failed == ["Cust.Ref."]


def test_run_flow_on_an_empty_fakturama_creates_contact_vat_and_products(order):
    app = FakeApp(tables={("select_address", "table"): grid(ADDRESS_COLUMNS)})
    result = run_flow(_ctx(order, app), STAGES)
    assert result.ok and [r.stage for r in result.completed] == ["1", "2", "3"]
    assert [s.number for s in result.not_built] == ["4", "5"]
    assert [s[0] for s in app.saved] == ["payment_editor", "debtor_editor", "vat_editor", "product_editor", "product_editor"]
    assert app.values[("order_editor", "subtotal")] == "$570.00" and app.values[("order_editor", "total")] == "$678.30"
    lines = format_run(result)
    assert "Stage 3 - Select or create each Product: passed" in lines
    assert "Stage 4 - Complete and save the Order: not built yet" in lines


def test_stages_without_code_are_listed_as_not_built(order):
    result = run_flow(_ctx(order, FakeApp()), [STAGES[0], Stage("4", "Complete and save the Order", None)])
    assert result.ok and [s.number for s in result.not_built] == ["4"]
    assert "Stage 4 - Complete and save the Order: not built yet" in format_run(result)


def test_run_flow_stops_at_the_first_stage_that_needs_review(order):
    ran = []

    def later(ctx):
        ran.append("later")

    stages = [Stage("1", "Open the New Order", open_order), Stage("2", "Next", later)]
    result = run_flow(_ctx(order, FakeApp(open_screens={"order_editor"})), stages)
    assert not result.ok and result.stopped_at.number == "1" and result.kind == "manual review"
    assert ran == []
    assert any("STOPPED (manual review)" in line for line in format_run(result))


def test_run_flow_reports_a_failed_check_with_its_details(order):
    def clear_reference(app):
        app.values[("order_editor", "cust_ref")] = ""

    app = FakeApp(after={("choose", "order_editor", "price_mode"): clear_reference})
    result = run_flow(_ctx(order, app), STAGES)
    assert result.kind == "check failed" and result.stage_result is not None
    assert any(line.strip().startswith("MISMATCH Cust.Ref.") for line in format_run(result))


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows message")
def test_cli_run_needs_windows(capsys, sample_image, sample_raw_path):
    assert main.main(["run", str(sample_image), "--raw", str(sample_raw_path)]) == 2
    assert "Windows" in capsys.readouterr().err
