from pathlib import Path

import pytest

from image_to_cash.extract.pipeline import load_raw_json
from image_to_cash.extract.schema import RawExtraction

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
SAMPLE_STEM = "order_WEB-2026-0714-A17"


@pytest.fixture
def sample_image() -> Path:
    return SAMPLES / f"{SAMPLE_STEM}.png"


@pytest.fixture
def sample_raw_path() -> Path:
    return SAMPLES / f"{SAMPLE_STEM}.raw.json"


@pytest.fixture
def sample_expected_path() -> Path:
    return SAMPLES / f"{SAMPLE_STEM}.expected.json"


@pytest.fixture
def raw(sample_raw_path) -> RawExtraction:
    """A fresh copy of the hand-checked transcription of the sample image; safe to mutate."""
    return load_raw_json(sample_raw_path)


@pytest.fixture
def sample_ocr_text(raw) -> str:
    """Text an OCR engine would return for the sample: every critical value, one per line."""
    from image_to_cash.extract.crosscheck import critical_values

    return "\n".join(value for _, value in critical_values(raw))
