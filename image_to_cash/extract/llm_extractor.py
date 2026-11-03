from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from image_to_cash.errors import ExtractionRejected, Issue
from image_to_cash.extract.schema import RawExtraction

SYSTEM_PROMPT = """\
You transcribe order documents (scans, photos, PDFs rendered as images) into a fixed JSON \
structure. The values feed an accounting system, so they must match the document exactly.

- Copy every value exactly as printed: same spelling, digits, punctuation, units and \
currency codes. Do not convert formats, calculate, translate or fill in missing parts.
- Use null for anything the document does not show.
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
        output_format=RawExtraction,
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
    raw = response.parsed_output
    if raw is None:
        raise _reject(f"Claude returned no structured output (stop_reason: {response.stop_reason})")

    usage = getattr(response, "usage", None)
    return LlmExtraction(
        raw=raw,
        model=getattr(response, "model", model),
        usage={
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )
