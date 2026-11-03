from __future__ import annotations

import io
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image


class OcrUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def center(self) -> tuple[float, float]:
        return self.left + self.width / 2, self.top + self.height / 2

    def scaled(self, factor: float) -> "Box":
        return Box(self.left * factor, self.top * factor, self.width * factor, self.height * factor)

    @staticmethod
    def union(boxes: Iterable["Box"]) -> "Box":
        boxes = list(boxes)
        left = min(b.left for b in boxes)
        top = min(b.top for b in boxes)
        return Box(left, top, max(b.right for b in boxes) - left, max(b.bottom for b in boxes) - top)


@dataclass(frozen=True)
class OcrWord:
    text: str
    box: Box


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: Box
    words: tuple[OcrWord, ...]


@dataclass
class OcrResult:
    engine: str
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def words(self) -> list[OcrWord]:
        return [w for line in self.lines for w in line.words]


def _engine_order() -> list[str]:
    if sys.platform == "win32":
        return ["windows", "tesseract"]
    if sys.platform == "darwin":
        return ["macos", "tesseract"]
    return ["tesseract"]


def _is_available(engine: str) -> bool:
    try:
        if engine == "windows":
            import winocr
        elif engine == "macos":
            import Vision
        elif engine == "tesseract":
            import pytesseract

            return shutil.which("tesseract") is not None
        else:
            return False
    except ImportError:
        return False
    return True


def available_engine() -> str | None:
    return next((e for e in _engine_order() if _is_available(e)), None)


def run_ocr(
    image: Image.Image | str | Path,
    *,
    engine: str | None = None,
    lang: str = "en",
    scale: float = 1.0,
) -> OcrResult:
    engine = engine or available_engine()
    if engine is None or not _is_available(engine):
        wanted = engine or " / ".join(_engine_order())
        raise OcrUnavailable(f"OCR engine not available on this machine: {wanted}")

    img = Image.open(image) if isinstance(image, (str, Path)) else image
    img = img.convert("RGB")
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)

    runner = {"windows": _ocr_windows, "macos": _ocr_macos, "tesseract": _ocr_tesseract}[engine]
    lines = runner(img, lang)
    if scale != 1.0:
        back = 1 / scale
        lines = [
            OcrLine(l.text, l.box.scaled(back), tuple(OcrWord(w.text, w.box.scaled(back)) for w in l.words))
            for l in lines
        ]
    return OcrResult(engine=engine, lines=lines)


def _ocr_windows(img: Image.Image, lang: str) -> list[OcrLine]:
    import winocr

    try:
        result = winocr.recognize_pil_sync(img, lang)
    except AssertionError as exc:
        raise OcrUnavailable(f"Windows OCR language '{lang}' is not installed. Run in admin PowerShell: {exc}")

    lines = []
    for line in result.get("lines") or []:
        words = tuple(
            OcrWord(
                w["text"],
                Box(w["bounding_rect"]["x"], w["bounding_rect"]["y"],
                    w["bounding_rect"]["width"], w["bounding_rect"]["height"]),
            )
            for w in line.get("words") or []
        )
        if words:
            lines.append(OcrLine(line["text"], Box.union(w.box for w in words), words))
    return lines


def _ocr_macos(img: Image.Image, lang: str) -> list[OcrLine]:
    import Vision
    from Foundation import NSData

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise OcrUnavailable(f"Apple Vision OCR failed: {error}")

    width, height = img.size

    def to_box(rect) -> Box:
        x, y = rect.origin.x, rect.origin.y
        w, h = rect.size.width, rect.size.height
        return Box(x * width, (1 - y - h) * height, w * width, h * height)

    lines = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        candidate = candidates[0]
        text = str(candidate.string())
        line_box = to_box(observation.boundingBox())
        words = []
        for m in re.finditer(r"\S+", text):
            word_obs, _ = candidate.boundingBoxForRange_error_((m.start(), m.end() - m.start()), None)
            words.append(OcrWord(m.group(), to_box(word_obs.boundingBox()) if word_obs else line_box))
        lines.append(OcrLine(text, line_box, tuple(words)))
    return lines


def _ocr_tesseract(img: Image.Image, lang: str) -> list[OcrLine]:
    import pytesseract

    tess_lang = {"en": "eng", "de": "deu"}.get(lang, lang)
    d = pytesseract.image_to_data(img, lang=tess_lang, output_type=pytesseract.Output.DICT)
    groups: dict[tuple[int, int, int], list[OcrWord]] = {}
    for i, text in enumerate(d["text"]):
        if not text.strip():
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        box = Box(d["left"][i], d["top"][i], d["width"][i], d["height"][i])
        groups.setdefault(key, []).append(OcrWord(text, box))
    return [
        OcrLine(" ".join(w.text for w in words), Box.union(w.box for w in words), tuple(words))
        for words in groups.values()
    ]
