from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    field: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"[{self.level}] {self.field}: {self.message}"


class FlowStopped(Exception):
    pass


class ExtractionRejected(FlowStopped):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        errors = [i for i in issues if i.level == "error"]
        lines = "\n".join(f"  - {i}" for i in errors)
        super().__init__(f"Extraction rejected ({len(errors)} error(s)):\n{lines}")


class ManualReviewRequired(FlowStopped):
    pass


class ControlNotFound(FlowStopped):
    pass


class VerificationFailed(FlowStopped):
    pass


class WaitTimeout(FlowStopped):
    pass


class NotBuiltYet(FlowStopped):
    def __init__(self, message: str, result=None):
        super().__init__(message)
        self.result = result
