from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from image_to_cash.errors import FlowStopped, ManualReviewRequired, NotBuiltYet, VerificationFailed
from image_to_cash.extract.schema import OrderData
from image_to_cash.settings import Settings


@dataclass(frozen=True)
class Check:
    what: str
    expected: str
    shown: str
    ok: bool

    def __str__(self) -> str:
        mark = "ok" if self.ok else "MISMATCH"
        return f"{mark:8s} {self.what}: expected {self.expected!r}, Fakturama shows {self.shown!r}"


@dataclass
class StageResult:
    stage: str
    title: str
    checks: list[Check]
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


class GateFailed(VerificationFailed):
    def __init__(self, result: StageResult):
        self.result = result
        failed = "; ".join(f"{c.what}: expected {c.expected!r}, shows {c.shown!r}" for c in result.checks if not c.ok)
        super().__init__(f"stage {result.stage} ({result.title}) check failed: {failed}")


def gate(stage: str, title: str, checks: list[Check], notes: list[str] | None = None) -> StageResult:
    result = StageResult(stage, title, list(checks), list(notes or []))
    if not result.ok:
        raise GateFailed(result)
    return result


@dataclass
class RunContext:
    order: OrderData
    app: Any
    settings: Settings
    order_number: str | None = None
    order_title: str | None = None
    invoice_number: str | None = None
    results: list[StageResult] = field(default_factory=list)


@dataclass(frozen=True)
class Stage:
    number: str
    title: str
    run: Callable[[RunContext], StageResult] | None


@dataclass
class RunResult:
    completed: list[StageResult]
    stopped_at: Stage | None = None
    kind: str | None = None
    reason: str | None = None
    stage_result: StageResult | None = None
    not_built: list[Stage] = field(default_factory=list)
    trace: str | None = None

    @property
    def ok(self) -> bool:
        return self.stopped_at is None


def run_flow(ctx: RunContext, stages: list[Stage],
             after_stage: Callable[[Stage, str], None] | None = None) -> RunResult:
    def stopped(stage: Stage, kind: str, reason: str, result: StageResult | None = None,
                trace: str | None = None) -> RunResult:
        if after_stage is not None:
            after_stage(stage, kind)
        return RunResult(ctx.results, stage, kind, reason, result, trace=trace)

    for index, stage in enumerate(stages):
        if stage.run is None:
            return RunResult(ctx.results, not_built=[s for s in stages[index:] if s.run is None])
        try:
            result = stage.run(ctx)
        except GateFailed as exc:
            return stopped(stage, "check failed", str(exc), exc.result)
        except ManualReviewRequired as exc:
            return stopped(stage, "manual review", str(exc))
        except NotBuiltYet as exc:
            return stopped(stage, "not built yet", str(exc), exc.result)
        except FlowStopped as exc:
            return stopped(stage, "stopped", str(exc))
        except Exception as exc:
            return stopped(stage, "error", f"{type(exc).__name__}: {exc}", trace=traceback.format_exc())
        ctx.results.append(result)
        if after_stage is not None:
            after_stage(stage, "passed")
    return RunResult(ctx.results)


def format_run(result: RunResult) -> list[str]:
    lines = []
    for stage in result.completed:
        lines.append(f"Stage {stage.stage} - {stage.title}: passed")
        lines += [f"    {c}" for c in stage.checks]
        lines += [f"    note: {n}" for n in stage.notes]
    if result.stopped_at is not None:
        lines.append(f"Stage {result.stopped_at.number} - {result.stopped_at.title}: STOPPED ({result.kind})")
        if result.stage_result is not None:
            lines += [f"    {c}" for c in result.stage_result.checks]
        lines.append(f"    {result.reason}")
    for stage in result.not_built:
        lines.append(f"Stage {stage.number} - {stage.title}: not built yet")
    return lines
