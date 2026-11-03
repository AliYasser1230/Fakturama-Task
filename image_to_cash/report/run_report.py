from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from image_to_cash.extract.schema import OrderData
from image_to_cash.flow.runner import Check, RunResult, Stage, StageResult, format_run

REVIEW_KINDS = {"manual review", "check failed", "stopped", "error"}
NEXT_STEP = {
    "manual review": "Fakturama shows something the task's rules cannot decide (see reason). Resolve it in "
                     "Fakturama, then run again.",
    "check failed": "A value in Fakturama differs from the order (see the failed checks). Nothing after this "
                    "stage was done.",
    "stopped": "The run could not continue (see reason). Nothing after this stage was done.",
    "error": "An unexpected error (see trace). Nothing after this stage was done.",
}


def safe_part(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "run"


def run_folder(runs_dir: Path, started: datetime, reference: str) -> Path:
    base = runs_dir / f"{started:%Y%m%d-%H%M%S}-{safe_part(reference)}"
    folder, n = base, 2
    while folder.exists():
        folder = base.with_name(f"{base.name}-{n}")
        n += 1
    return folder


def check_dict(check: Check) -> dict[str, Any]:
    return {"what": check.what, "expected": check.expected, "shown": check.shown, "ok": check.ok}


def stage_dict(result: StageResult, status: str) -> dict[str, Any]:
    return {"stage": result.stage, "title": result.title, "status": status,
            "checks": [check_dict(c) for c in result.checks], "notes": list(result.notes)}


def outcome(result: RunResult) -> str:
    if result.stopped_at is None:
        return "partial" if result.not_built else "completed"
    return "partial" if result.kind == "not built yet" else "needs review"


def order_summary(order: OrderData) -> dict[str, Any]:
    return {
        "external_reference": order.external_reference,
        "order_date": order.order_date.isoformat(),
        "company": order.debtor.company,
        "items": [{"sku": i.sku, "quantity": str(i.quantity), "unit_net_price": str(i.unit_net_price)} for i in order.items],
        "totals": {"net": str(order.totals.net), "vat": str(order.totals.vat), "gross": str(order.totals.gross)},
        "currency": order.currency,
        "payment": {"method": order.payment.method.value, "status": order.payment.paid_status,
                    "date": order.payment.payment_date.isoformat() if order.payment.payment_date else None},
    }


class RunReport:
    def __init__(self, runs_dir: Path, order: OrderData, *, extraction: dict[str, Any] | None = None,
                 clock: Callable[[], datetime] = datetime.now, capture: Callable[[Path], None] | None = None):
        self.clock = clock
        self.started = clock()
        self.order = order
        self.extraction = extraction or {}
        self.capture_fn = capture
        self.folder = run_folder(Path(runs_dir), self.started, order.external_reference)
        self.folder.mkdir(parents=True)
        self.screenshots: list[dict[str, str]] = []
        (self.folder / "order.json").write_text(order.model_dump_json(indent=2), encoding="utf-8")

    def capture(self, label: str) -> None:
        if self.capture_fn is None:
            return
        name = f"{len(self.screenshots) + 1:02d}_{safe_part(label)}.png"
        path = self.folder / "screenshots" / name
        path.parent.mkdir(exist_ok=True)
        entry = {"file": f"screenshots/{name}", "label": label}
        try:
            self.capture_fn(path)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        self.screenshots.append(entry)

    def after_stage(self, stage: Stage, status: str) -> None:
        self.capture(f"stage{stage.number}_{status}")

    def finish(self, result: RunResult, *, fakturama: dict[str, Any] | None = None,
               open_editors: list[str] | None = None) -> Path:
        stages = [stage_dict(r, "passed") for r in result.completed]
        stopped = None
        if result.stopped_at is not None:
            stopped = {"stage": result.stopped_at.number, "title": result.stopped_at.title,
                       "kind": result.kind, "reason": result.reason}
            if result.stage_result is not None:
                stages.append(stage_dict(result.stage_result, result.kind))
            else:
                stages.append({"stage": result.stopped_at.number, "title": result.stopped_at.title,
                               "status": result.kind, "checks": [], "notes": []})
        report = {
            "started": self.started.isoformat(timespec="seconds"),
            "finished": self.clock().isoformat(timespec="seconds"),
            "outcome": outcome(result),
            "order": order_summary(self.order),
            "extraction": self.extraction,
            "fakturama": fakturama or {},
            "stages": stages,
            "stopped": stopped,
            "not_built": [f"{s.number} {s.title}" for s in result.not_built],
            "open_editors": open_editors or [],
            "screenshots": self.screenshots,
        }
        if result.trace:
            report["trace"] = result.trace
        self._write("report.json", json.dumps(report, indent=2, ensure_ascii=False))
        self._write("report.md", "\n".join(self.markdown(result, report)) + "\n")
        if result.stopped_at is not None and result.kind in REVIEW_KINDS:
            self._write("manual_review.json", json.dumps(self.review(result, report), indent=2, ensure_ascii=False))
        return self.folder

    def review(self, result: RunResult, report: dict[str, Any]) -> dict[str, Any]:
        failed = [check_dict(c) for c in (result.stage_result.checks if result.stage_result else []) if not c.ok]
        shots = [s["file"] for s in self.screenshots if "error" not in s]
        return {
            "order": self.order.external_reference,
            "stage": f"{result.stopped_at.number} {result.stopped_at.title}",
            "kind": result.kind,
            "reason": result.reason,
            "failed_checks": failed,
            "open_editors": report["open_editors"],
            "unsaved_editors": [n for n in report["open_editors"] if n.startswith("*")],
            "screenshot": shots[-1] if shots else None,
            "next_step": NEXT_STEP[result.kind],
        }

    def markdown(self, result: RunResult, report: dict[str, Any]) -> list[str]:
        order = report["order"]
        lines = [
            f"# Run {self.folder.name}",
            "",
            f"- Order: {order['external_reference']} ({order['order_date']}), {order['company']}, "
            f"{len(order['items'])} item(s), gross {order['totals']['gross']} {order['currency']}",
            f"- Payment: {order['payment']['method']}, {order['payment']['status']}",
            f"- Outcome: **{report['outcome']}**",
            f"- Started {report['started']}, finished {report['finished']}",
        ]
        if self.extraction:
            lines.append(f"- Extraction: {self.extraction.get('source')}, OCR {self.extraction.get('ocr_engine')}")
        if report["open_editors"]:
            lines.append(f"- Open editors left in Fakturama: {'; '.join(report['open_editors'])}")
        lines += ["", "## Stages", "", "```", *format_run(result), "```"]
        if report["screenshots"]:
            lines += ["", "## Screenshots", ""]
            lines += [f"- [{s['label']}]({s['file']})" + (f" (failed: {s['error']})" if "error" in s else "")
                      for s in report["screenshots"]]
        if result.trace:
            lines += ["", "## Error", "", "```", result.trace.rstrip(), "```"]
        return lines

    def _write(self, name: str, text: str) -> None:
        (self.folder / name).write_text(text, encoding="utf-8")
