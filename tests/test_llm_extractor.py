import base64
import io
import json
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
    assert call["output_format"] is llm_extractor.wire_model(RawExtraction)
    assert call["output_config"] == {"effort": "medium"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in call
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


def _sent_schema():
    from anthropic.lib._parse._transform import to_json_output_format

    return to_json_output_format(llm_extractor.wire_model(RawExtraction))["schema"]


def test_schema_is_accepted_by_the_sdk_structured_output_transform():
    schema = _sent_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(RawExtraction.model_fields)


def test_schema_sent_to_claude_has_no_optional_text_fields():
    text = json.dumps(_sent_schema())
    assert text.count('"anyOf"') == 1
    assert '"delivery_address": {"anyOf"' in text


def _blanks(value):
    if isinstance(value, dict):
        return {key: _blanks(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_blanks(item) for item in value]
    return "" if value is None else value


def test_empty_strings_from_claude_become_none(raw, sample_image):
    wire = llm_extractor.wire_model(RawExtraction).model_validate(_blanks(raw.model_dump()))
    assert wire.customer.salutation == ""
    result = llm_extractor.extract_raw(sample_image, model="m", effort="medium", client=FakeClient(_response(wire)))
    assert result.raw == raw
    assert result.raw.customer.salutation is None


def test_an_answer_that_does_not_fit_the_schema_is_rejected(raw, sample_image):
    broken =SimpleNamespace(model_dump=lambda: {**_blanks(raw.model_dump()), "order": "not an object"})
    with pytest.raises(ExtractionRejected, match="does not fit the order schema"):
        llm_extractor.extract_raw(sample_image, model="m", effort="medium", client=FakeClient(_response(broken)))


def test_large_or_unsupported_images_are_converted(tmp_path):
    path = tmp_path / "scan.bmp"
    Image.new("RGB", (3000, 1000), "white").save(path)
    media_type, data = llm_extractor.encode_image(path)
    assert media_type == "image/png"
    with Image.open(io.BytesIO(base64.standard_b64decode(data))) as img:
        assert max(img.size) <= 2400
