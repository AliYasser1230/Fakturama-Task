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
    issues: list[Issue] = field(default_factory=list)
    source: str = ""
    ocr_engine: str | None = None
    llm_usage: dict[str, Any] = field(default_factory=dict)


def extract_order(
    image_path: str | Path,
    *,
    settings: Settings,
    raw: RawExtraction | None = None,
    client: Any = None,
) -> ExtractionResult:
    issues: list[Issue] = []
    usage: dict[str, Any] = {}

    if raw is None:
        llm = extract_raw(image_path, model=settings.extraction_model,
                          effort=settings.extraction_effort, client=client)
        raw, source, usage = llm.raw, f"claude:{llm.model}", llm.usage
    else:
        source = "raw-json"

    try:
        ocr = run_ocr(image_path, lang=settings.ocr_language)
    except OcrUnavailable as exc:
        raise ExtractionRejected([Issue("error", "ocr", str(exc))])
    issues += crosscheck(raw, ocr.text)

    order, norm_issues = normalize(raw)
    issues += norm_issues
    if order is not None:
        issues += validate(order, expected_currency=settings.expected_currency)

    if order is None or any(i.level == "error" for i in issues):
        raise ExtractionRejected(issues)

    return ExtractionResult(order=order, raw=raw, issues=issues, source=source,
                            ocr_engine=ocr.engine, llm_usage=usage)


def load_raw_json(path: str | Path) -> RawExtraction:
    return RawExtraction.model_validate_json(Path(path).read_text(encoding="utf-8"))

