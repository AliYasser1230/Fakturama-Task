import argparse
import json
import sys
from decimal import Decimal

import pytest

import main
from image_to_cash.errors import ExtractionRejected
from image_to_cash.extract import pipeline
from image_to_cash.ocr import Box, OcrLine, OcrResult, OcrUnavailable, OcrWord
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
    assert fields == {"items[0]", "totals.net", "totals.vat"}


def test_no_ocr_engine_rejects_the_order(monkeypatch, raw, sample_image):
    def no_ocr(image, **kwargs):
        raise OcrUnavailable("Windows OCR is not available on this machine")

    monkeypatch.setattr(pipeline, "run_ocr", no_ocr)
    with pytest.raises(ExtractionRejected) as exc:
        pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw)
    assert [i.field for i in exc.value.issues] == ["ocr"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR runs on Windows only")
def test_real_ocr_on_the_sample_image(raw, sample_image):
    result = pipeline.extract_order(sample_image, settings=SETTINGS, raw=raw)
    assert result.ocr_engine == "windows"
    assert all(i.level == "warning" and i.field.endswith((".discount", ".vat")) for i in result.issues)


def _args(image, raw=None):
    return argparse.Namespace(image=str(image), raw=str(raw) if raw else None)


def test_run_command_takes_the_image_and_an_optional_raw_file():
    args = main.build_parser().parse_args(["run", "order.png", "--raw", "order.raw.json"])
    assert (args.image, args.raw, args.func) == ("order.png", "order.raw.json", main.cmd_run)
    assert main.build_parser().parse_args(["run", "order.png"]).raw is None
    with pytest.raises(SystemExit):
        main.build_parser().parse_args(["run"])


def test_load_order_with_raw_gives_the_expected_order(monkeypatch, sample_image, sample_raw_path,
                                                      sample_expected_path, sample_ocr_text):
    monkeypatch.setattr(pipeline, "run_ocr", _fake_ocr(sample_ocr_text))
    order, issues, info = main._load_order(_args(sample_image, sample_raw_path), SETTINGS)
    assert json.loads(order.model_dump_json()) == json.loads(sample_expected_path.read_text())
    assert issues == [] and info["source"] == "raw-json" and info["ocr_engine"] == "fake"


def test_load_order_without_api_key_explains_instead_of_crashing(monkeypatch, capsys, sample_image):
    def no_credentials(*args, **kwargs):
        raise TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token, ..."')

    monkeypatch.setattr(pipeline, "extract_raw", no_credentials)
    assert main._load_order(_args(sample_image), SETTINGS) == (None, [], {})
    err = capsys.readouterr().err
    assert "No Claude API key found" in err and "--raw" in err


def test_load_order_rejects_a_wrong_total(monkeypatch, tmp_path, capsys, sample_image, raw, sample_ocr_text):
    monkeypatch.setattr(pipeline, "run_ocr", _fake_ocr(sample_ocr_text))
    raw.totals.gross_total = "EUR 999.00"
    bad = tmp_path / "bad.raw.json"
    bad.write_text(raw.model_dump_json())
    assert main._load_order(_args(sample_image, bad), SETTINGS) == (None, [], {})
    assert "REJECTED" in capsys.readouterr().err
