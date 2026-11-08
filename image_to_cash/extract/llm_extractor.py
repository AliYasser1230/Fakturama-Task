from __future__ import annotations

import base64
import io
import types
import typing
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from image_to_cash.errors import ExtractionRejected, Issue
from image_to_cash.extract.schema import RawExtraction

SYSTEM_PROMPT = """\
You transcribe order documents (scans, photos, PDFs rendered as images) into a fixed JSON \
structure. The values feed an accounting system, so they must match the document exactly.

- Copy every value exactly as printed: same spelling, digits, punctuation, units and \
currency codes. Do not convert formats, calculate, translate or fill in missing parts.
- Use an empty string for any text the document does not show.
- If a value is printed but you cannot read it with confidence, still give your best \
reading and add its path (for example "items[1].unit_net_price") to unreadable_fields.
- items: one entry per printed item row, in printed order. Skip empty table rows.
- Addresses: split each printed address block into its parts; the first line (company \
or recipient name) goes into name.
- delivery_address: null if no separate delivery address is printed.
- totals.order_discount and totals.shipping: only when the document prints an \
order-level discount or a shipping charge.
"""

USER_PROMPT = "Transcribe this order document."

_MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
_MAX_RAW_BYTES = 3_750_000
_MAX_EDGE_WHEN_SHRINKING = 2400

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@cache
def wire_model(model: type[BaseModel]) -> type[BaseModel]:
    fields = {name: (wire_type(info.annotation), Field(description=info.description))
              for name, info in model.model_fields.items()}
    return create_model(model.__name__, __config__=ConfigDict(extra="forbid"), **fields)


def wire_type(annotation: Any) -> Any:
    args = typing.get_args(annotation)
    if typing.get_origin(annotation) in (types.UnionType, typing.Union) and type(None) in args:
        inner = next(a for a in args if a is not type(None))
        return str if inner is str else wire_type(inner) | None
    if typing.get_origin(annotation) is list:
        return list[wire_type(args[0])]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return wire_model(annotation)
    return annotation


def blanks_to_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: blanks_to_none(item) for key, item in value.items()}
    if isinstance(value, list):
        return [blanks_to_none(item) for item in value if not (isinstance(item, str) and not item.strip())]
    if isinstance(value, str) and not value.strip():
        return None
    return value


@dataclass
class LlmExtraction:
    raw: RawExtraction
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


def encode_image(path: str | Path) -> tuple[str, str]:
    path = Path(path)
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as img:
        media_type = _MEDIA_TYPES.get(img.format or "")
        if media_type and len(data) <= _MAX_RAW_BYTES:
            return media_type, base64.standard_b64encode(data).decode("ascii")

        img = img.convert("RGB")
        img.thumbnail((_MAX_EDGE_WHEN_SHRINKING, _MAX_EDGE_WHEN_SHRINKING))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        if buf.tell() > _MAX_RAW_BYTES:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return "image/png", base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _reject(message: str) -> ExtractionRejected:
    return ExtractionRejected([Issue("error", "llm", message)])


def extract_raw(
    image_path: str | Path,
    *,
    model: str,
    effort: str,
    client: Any = None,
) -> LlmExtraction:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    media_type, data = encode_image(image_path)
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": effort},
        output_format=wire_model(RawExtraction),
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": USER_PROMPT},
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise _reject(f"Claude declined to read the image (category: {category or 'unspecified'})")
    if response.stop_reason == "max_tokens":
        raise _reject("Claude's answer was cut off (max_tokens); the transcription is incomplete")
    if response.parsed_output is None:
        raise _reject(f"Claude returned no structured output (stop_reason: {response.stop_reason})")
    try:
        raw = RawExtraction.model_validate(blanks_to_none(response.parsed_output.model_dump()))
    except ValidationError as exc:
        raise _reject(f"Claude's answer does not fit the order schema: {exc}") from None

    usage = getattr(response, "usage", None)
    return LlmExtraction(
        raw=raw,
        model=getattr(response, "model", model),
        usage={
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )
