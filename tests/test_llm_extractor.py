"""The Claude call, tested with a fake client: no network, no API key."""

import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from image_to_cash.errors import ExtractionRejected
from image_to_cash.extract import llm_extractor
from image_to_cash.extract.schema import RawExtraction


class FakeClient:
    def __init__(self, response):
        self.calls = []
        self.response = response
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _response(raw=None, stop_reason="end_turn", **extra):
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=raw,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1500, output_tokens=900),
        stop_details=extra.get("stop_details"),
    )


def test_request_shape(raw, sample_image):
    client = FakeClient(_response(raw))
    result = llm_extractor.extract_raw(sample_image, model="claude-opus-5-5", effort="medium", client=client)

    assert result.raw == raw and result.model == "claude-opus-5-5"
    assert result.usage == {"input_tokens": 1500, "output_tokens": 900}
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is RawExtraction
    assert call["output_config"] == {"effort": "medium"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in call  # rejected by current models
    image_block, text_block = call["messages"][0]["content"]
    assert image_block["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(image_block["source"]["data"]) == sample_image.read_bytes()
    assert text_block["type"] == "text"


@pytest.mark.parametrize(
    "response, message",
    [
        (_response(None, "refusal", stop_details=SimpleNamespace(category="cyber")), "declined"),
        (_response(None, "max_tokens"), "cut off"),
        (_response(None, "end_turn"), "no structured output"),
    ],
)
def test_unusable_responses_are_rejected(sample_image, response, message):
    with pytest.raises(ExtractionRejected) as exc:
        llm_extractor.extract_raw(sample_image, model="m", effort="medium", client=FakeClient(response))
    assert message in str(exc.value)


def test_schema_is_accepted_by_the_sdk_structured_output_transform():
    from anthropic.lib._parse._transform import transform_schema

    schema = transform_schema(RawExtraction)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(RawExtraction.model_fields)


def test_large_or_unsupported_images_are_converted(tmp_path):
    path = tmp_path / "scan.bmp"
    Image.new("RGB", (3000, 1000), "white").save(path)
    media_type, data = llm_extractor.encode_image(path)
    assert media_type == "image/png"
    with Image.open(io.BytesIO(base64.standard_b64decode(data))) as img:
        assert max(img.size) <= 2400
