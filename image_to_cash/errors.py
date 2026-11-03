"""
Exceptions that stop the flow. Each one ends the run and writes the report.

- ExtractionRejected: the image data failed a check; Fakturama is never touched.
- ManualReviewRequired: ambiguous or conflicting match
  (spec 2.3, 2.10.2, 3.3, 3.5, 3.12, 5.2).
- ControlNotFound: a UI control did not appear within its timeout.
- VerificationFailed: a value read back from the UI differs from the expected one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    """One finding from extraction. Errors stop the run; warnings are only reported."""

    level: Literal["error", "warning"]
    field: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"[{self.level}] {self.field}: {self.message}"


class FlowStopped(Exception):
    """Base class: the run stops here and the report says why."""


class ExtractionRejected(FlowStopped):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        errors = [i for i in issues if i.level == "error"]
        lines = "\n".join(f"  - {i}" for i in errors)
        super().__init__(f"Extraction rejected ({len(errors)} error(s)):\n{lines}")


class ManualReviewRequired(FlowStopped):
    """An exact, unambiguous choice was not possible; a person has to decide."""


class ControlNotFound(FlowStopped):
    """A UI control did not appear within its timeout, even with fallbacks."""


class VerificationFailed(FlowStopped):
    """A value read back from Fakturama differs from what was expected."""
