"""
Run settings: Claude model, timeouts, paths.

Values come from environment variables or a local .env file (see .env.example).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    extraction_model: str = "claude-opus-5-5"
    # Effort for the extraction call. Transcription is easy for the model; "medium" keeps
    # it careful without paying for deep reasoning.
    extraction_effort: str = "medium"
    # Fakturama's document currency. An image in another currency is rejected.
    expected_currency: str = "EUR"
    # Language of the OCR engine (Windows OCR / Tesseract / Apple Vision).
    ocr_language: str = "en"
    fakturama_exe: str | None = None
    runs_dir: Path = PROJECT_ROOT / "runs"
    locators_file: Path = PROJECT_ROOT / "config" / "locators.yaml"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        defaults = cls()
        return cls(
            extraction_model=os.getenv("EXTRACTION_MODEL") or defaults.extraction_model,
            extraction_effort=os.getenv("EXTRACTION_EFFORT") or defaults.extraction_effort,
            expected_currency=os.getenv("EXPECTED_CURRENCY") or defaults.expected_currency,
            ocr_language=os.getenv("OCR_LANGUAGE") or defaults.ocr_language,
            fakturama_exe=os.getenv("FAKTURAMA_EXE") or None,
        )
