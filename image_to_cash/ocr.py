from __future__ import annotations

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


def run_ocr(
    image: Image.Image | str | Path,
    *,
    lang: str = "en",
    scale: float = 1.0,
) -> OcrResult:
    img = Image.open(image) if isinstance(image, (str, Path)) else image
    img = img.convert("RGB")
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)

    lines = _ocr_windows(img, lang)
    if scale != 1.0:
        back = 1 / scale
        lines = [
            OcrLine(l.text, l.box.scaled(back), tuple(OcrWord(w.text, w.box.scaled(back)) for w in l.words))
            for l in lines
        ]
    return OcrResult(engine="windows", lines=lines)


def _ocr_windows(img: Image.Image, lang: str) -> list[OcrLine]:
    try:
        import winocr
    except ImportError:
        raise OcrUnavailable("Windows OCR is not available on this machine (winocr is installed on Windows only)")

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

