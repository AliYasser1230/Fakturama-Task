import json
from decimal import Decimal

import pytest

import main
from image_to_cash.errors import ExtractionRejected
from image_to_cash.extract import pipeline
from image_to_cash.ocr import Box, OcrLine, OcrResult, OcrWord, available_engine
from image_to_cash.settings import Settings

SETTINGS = Settings()


def _fake_ocr(text):
    def run_ocr(image, **kwargs):
        lines = [OcrLine(t, Box(0, 0, 1, 1), (OcrWord(t, Box(0, 0, 1, 1)),)) for t in text.splitlines()]
        return OcrResult(engine="fake", lines=lines)
    return run_ocr


def test_pipeline_accepts_the_sample(monkeypatch, raw, sample_image, sample_ocr_text):
    monkeypatch.setattr(pipeline, "run_ocr", _fake_ocr(sample_ocr_text))
    result = pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw)
    assert result.order.totals.gross == Decimal("678.30")
    assert result.source == "raw-json" and result.ocr_engine == "fake"
    assert result.issues == []


def test_pipeline_rejects_value_missing_from_ocr(monkeypatch, raw, sample_image, sample_ocr_text):
    monkeypatch.setattr(pipeline, "run_ocr", _fake_ocr(sample_ocr_text.replace("MAT-DESK-02", "")))
    with pytest.raises(ExtractionRejected) as exc:
        pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw)
    assert [i.field for i in exc.value.issues if i.level == "error"] == ["items[1].sku"]


def test_pipeline_reports_normalize_and_validate_errors_together(monkeypatch, raw, sample_image, sample_ocr_text):
    monkeypatch.setattr(pipeline, "run_ocr", _fake_ocr(sample_ocr_text + "\n460.00"))
    raw.items[0].line_net = "460.00"
    with pytest.raises(ExtractionRejected) as exc:
        pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw)
    fields = {i.field.split(" ")[0] for i in exc.value.issues if i.level == "error"}
    # One wrong line total breaks the line check, the net sum and the VAT computed from the lines.
    assert fields == {"items[0]", "totals.net", "totals.vat"}


def test_skipping_ocr_is_a_visible_warning(raw, sample_image):
    result = pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw, ocr_check=False)
    assert any(i.field == "ocr" and i.level == "warning" for i in result.issues)


def test_load_order_json_revalidates(tmp_path, sample_expected_path):
    assert pipeline.load_order_json(sample_expected_path, settings=SETTINGS).items[0].sku == "CHR-ERG-01"
    data = json.loads(sample_expected_path.read_text())
    data["totals"]["gross"] = "700.00"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(data))
    with pytest.raises(ExtractionRejected):
        pipeline.load_order_json(edited, settings=SETTINGS)


@pytest.mark.skipif(available_engine() is None, reason="no OCR engine on this machine")
def test_real_ocr_on_the_sample_image(raw, sample_image):
    """End to end with the real OCR engine of this OS (Apple Vision on Mac, Windows OCR on Windows)."""
    result = pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw)
    assert result.ocr_engine in {"macos", "windows", "tesseract"}
    assert result.issues == []


def test_cli_extract_writes_order_json(tmp_path, capsys, sample_image, sample_raw_path, sample_expected_path):
    out = tmp_path / "order.json"
    code = main.main(["extract", str(sample_image), "--raw", str(sample_raw_path), "--no-ocr-check", "--out", str(out)])
    assert code == 0
    assert json.loads(out.read_text()) == json.loads(sample_expected_path.read_text())
    assert "OK: WEB-2026-0714-A17" in capsys.readouterr().err


def test_cli_extract_without_api_key_explains_instead_of_crashing(monkeypatch, capsys, sample_image):
    def no_credentials(*args, **kwargs):
        # What the SDK raises when no API key, token or profile is configured.
        raise TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token, ..."')

    monkeypatch.setattr(pipeline, "extract_raw", no_credentials)  # never reaches the network
    assert main.main(["extract", str(sample_image), "--no-ocr-check"]) == 1
    err = capsys.readouterr().err
    assert "No Claude API key found" in err and "--raw" in err


def test_cli_extract_rejected_exit_code(tmp_path, capsys, sample_image, raw):
    raw.totals.gross_total = "EUR 999.00"
    bad = tmp_path / "bad.raw.json"
    bad.write_text(raw.model_dump_json())
    code = main.main(["extract", str(sample_image), "--raw", str(bad), "--no-ocr-check"])
    assert code == 1
    assert "REJECTED" in capsys.readouterr().err
