import json
from datetime import datetime, timedelta

import pytest

from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.order import open_order
from image_to_cash.flow.runner import RunContext, Stage, run_flow
from image_to_cash.flow.stages import STAGES
from image_to_cash.report.run_report import RunReport, outcome, run_folder
from image_to_cash.settings import Settings
from tests.fakes import ADDRESS_COLUMNS, FakeApp, grid


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 3, 15, 30, 0)

    def __call__(self):
        self.now += timedelta(seconds=7)
        return self.now


@pytest.fixture
def order(sample_expected_path):
    return OrderData.model_validate_json(sample_expected_path.read_text(encoding="utf-8"))


def _fake_png(path):
    path.write_bytes(b"\x89PNG fake")


def _run(tmp_path, order, app, stages=STAGES, capture=_fake_png, open_editors=None):
    report = RunReport(tmp_path, order, extraction={"source": "raw-json", "ocr_engine": "windows"},
                       clock=Clock(), capture=capture)
    report.capture("start")
    result = run_flow(RunContext(order=order, app=app, settings=Settings()), stages, after_stage=report.after_stage)
    folder = report.finish(result, fakturama={"title": "Fakturama - C:\\FakturamaData"}, open_editors=open_editors)
    return result, folder, json.loads((folder / "report.json").read_text(encoding="utf-8"))


def test_completed_run_writes_report_order_and_screenshots_but_no_review(tmp_path, order):
    app = FakeApp(tables={("select_address", "table"): grid(ADDRESS_COLUMNS)})
    result, folder, data = _run(tmp_path, order, app, open_editors=["PO000001", "INV000001"])
    assert folder.name == "20261103-153007-WEB-2026-0714-A17"
    assert data["outcome"] == "completed"
    assert [(s["stage"], s["status"]) for s in data["stages"]] == [(n, "passed") for n in "12345"]
    assert data["stopped"] is None and data["not_built"] == []
    assert len(data["stages"][0]["checks"]) == 6 and all(c["ok"] for s in data["stages"] for c in s["checks"])
    assert [s["label"] for s in data["screenshots"]] == ["start"] + [f"stage{n}_passed" for n in "12345"]
    assert all((folder / s["file"]).is_file() for s in data["screenshots"])
    assert (folder / "order.json").is_file() and not (folder / "manual_review.json").exists()
    md = (folder / "report.md").read_text(encoding="utf-8")
    assert "- Outcome: **completed**" in md and "Stage 5 - Complete and verify the linked Invoice: passed" in md
    assert "Open editors left in Fakturama: PO000001; INV000001" in md


def test_manual_review_stop_writes_what_a_person_needs(tmp_path, order):
    app = FakeApp(open_screens={"order_editor"})
    result, folder, data = _run(tmp_path, order, app, open_editors=["*New Order"])
    assert data["outcome"] == "needs review"
    review = json.loads((folder / "manual_review.json").read_text(encoding="utf-8"))
    assert review["stage"] == "1 Open the New Order" and review["kind"] == "manual review"
    assert "already open" in review["reason"]
    assert review["unsaved_editors"] == ["*New Order"]
    assert review["screenshot"] == "screenshots/02_stage1_manual_review.png"
    assert "Resolve it in Fakturama" in review["next_step"]


def test_failed_check_lists_the_fields_that_differ(tmp_path, order):
    def clear_reference(app):
        app.values[("order_editor", "cust_ref")] = ""

    app = FakeApp(after={("choose", "order_editor", "price_mode"): clear_reference})
    _, folder, data = _run(tmp_path, order, app)
    review = json.loads((folder / "manual_review.json").read_text(encoding="utf-8"))
    assert review["kind"] == "check failed"
    assert [c["what"] for c in review["failed_checks"]] == ["Cust.Ref."]
    assert data["stages"][0]["status"] == "check failed"


def test_unexpected_error_is_reported_with_its_trace(tmp_path, order):
    def broken(ctx):
        raise RuntimeError("COM element vanished")

    _, folder, data = _run(tmp_path, order, FakeApp(), stages=[Stage("1", "Open the New Order", broken)])
    assert data["stopped"] == {"stage": "1", "title": "Open the New Order", "kind": "error",
                               "reason": "RuntimeError: COM element vanished"}
    assert "Traceback" in data["trace"]
    assert "## Error" in (folder / "report.md").read_text(encoding="utf-8")
    assert json.loads((folder / "manual_review.json").read_text(encoding="utf-8"))["kind"] == "error"


def test_a_failing_screenshot_is_recorded_and_the_run_goes_on(tmp_path, order):
    def no_screen(path):
        raise OSError("screen locked")

    result, _, data = _run(tmp_path, order, FakeApp(), stages=[Stage("1", "Open the New Order", open_order)],
                           capture=no_screen)
    assert result.ok
    assert all(s["error"] == "OSError: screen locked" for s in data["screenshots"])


def test_run_folder_names_are_safe_and_unique(tmp_path):
    started = datetime(2026, 11, 3, 15, 30, 0)
    first = run_folder(tmp_path, started, "WEB 2026/07:14")
    assert first.name == "20261103-153000-WEB_2026_07_14"
    first.mkdir()
    assert run_folder(tmp_path, started, "WEB 2026/07:14").name == "20261103-153000-WEB_2026_07_14-2"


def test_outcome():
    from image_to_cash.flow.runner import RunResult

    stage = Stage("2", "x", None)
    assert outcome(RunResult([])) == "completed"
    assert outcome(RunResult([], not_built=[stage])) == "partial"
    assert outcome(RunResult([], stage, "not built yet", "r")) == "partial"
    assert outcome(RunResult([], stage, "manual review", "r")) == "needs review"


def test_runner_calls_the_hook_after_each_stage(order):
    seen = []
    app = FakeApp(tables={("select_address", "table"): grid(ADDRESS_COLUMNS)})
    run_flow(RunContext(order=order, app=app, settings=Settings()), STAGES,
             after_stage=lambda stage, status: seen.append((stage.number, status)))
    assert seen == [(n, "passed") for n in "12345"]
