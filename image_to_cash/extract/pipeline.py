"""
Runs steps A -> B -> C -> D and returns a validated order, or raises ExtractionRejected.

    A  llm_extractor  Claude transcribes the image (skipped when a saved raw JSON is given)
    B  crosscheck     critical values must appear in the OCR text
    C  normalize      verbatim strings -> typed OrderData
    D  validate       arithmetic and consistency checks

Also loads a previously saved order JSON so the UI flow can run without an API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from image_to_cash.errors import ExtractionRejected, Issue
from image_to_cash.extract.crosscheck import crosscheck
from image_to_cash.extract.llm_extractor import extract_raw
from image_to_cash.extract.normalize import normalize
from image_to_cash.extract.schema import OrderData, RawExtraction
from image_to_cash.extract.validate import validate
from image_to_cash.ocr import OcrUnavailable, run_ocr
from image_to_cash.settings import Settings


@dataclass
class ExtractionResult:
    order: OrderData
    raw: RawExtraction
    issues: list[Issue] = field(default_factory=list)  # warnings only; errors raise
    source: str = ""  # "claude:<model>" or "raw-json"
    ocr_engine: str | None = None
    llm_usage: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ocr_engine": self.ocr_engine,
            "llm_usage": self.llm_usage,
            "warnings": [i.to_dict() for i in self.issues],
        }


def extract_order(
    image_path: str | Path,
    *,
    settings: Settings,
    raw: RawExtraction | None = None,
    ocr_check: bool = True,
    client: Any = None,
) -> ExtractionResult:
    issues: list[Issue] = []
    usage: dict[str, Any] = {}

    # A: transcription
    if raw is None:
        llm = extract_raw(image_path, model=settings.extraction_model,
                          effort=settings.extraction_effort, client=client)
        raw, source, usage = llm.raw, f"claude:{llm.model}", llm.usage
    else:
        source = "raw-json"

    # B: OCR cross-check
    ocr_engine = None
    if ocr_check:
        try:
            ocr = run_ocr(image_path, lang=settings.ocr_language)
        except OcrUnavailable as exc:
            raise ExtractionRejected([Issue("error", "ocr", f"{exc}. Use --no-ocr-check to skip at your own risk.")])
        ocr_engine = ocr.engine
        issues += crosscheck(raw, ocr.text)
    else:
        issues.append(Issue("warning", "ocr", "OCR cross-check skipped (--no-ocr-check)"))

    # C + D: normalize, then check the arithmetic
    order, norm_issues = normalize(raw)
    issues += norm_issues
    if order is not None:
        issues += validate(order, expected_currency=settings.expected_currency)

    if order is None or any(i.level == "error" for i in issues):
        raise ExtractionRejected(issues)

    return ExtractionResult(order=order, raw=raw, issues=issues, source=source,
                            ocr_engine=ocr_engine, llm_usage=usage)


def load_raw_json(path: str | Path) -> RawExtraction:
    return RawExtraction.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_order_json(path: str | Path, *, settings: Settings) -> OrderData:
    """Load a saved OrderData JSON and re-run the step D checks, so an edited file cannot skip them."""
    order = OrderData.model_validate_json(Path(path).read_text(encoding="utf-8"))
    issues = validate(order, expected_currency=settings.expected_currency)
    if any(i.level == "error" for i in issues):
        raise ExtractionRejected(issues)
    return order
