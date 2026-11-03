from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable

from image_to_cash.errors import ControlNotFound
from image_to_cash.extract.crosscheck import fold
from image_to_cash.ocr import Box, OcrWord

ELLIPSIS = ("...", "…")
HEADER_PAD = 4.0
MAX_HEADER_WORDS = 4
GRID_LINE_NOISE = re.compile(r"[Il|!]+")


def header_key(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", fold(text))


def cell_key(text: str) -> str:
    return fold(text)


def cell_matches(shown: str, expected: str) -> str | None:
    shown = " ".join((shown or "").split())
    expected = " ".join((expected or "").split())
    if cell_key(shown) == cell_key(expected):
        return "exact"
    for mark in ELLIPSIS:
        if shown.endswith(mark):
            stem = cell_key(shown[: -len(mark)])
            if stem and cell_key(expected).startswith(stem):
                return "truncated"
    return None


@dataclass(frozen=True)
class GridRow:
    cells: dict[str, str]
    box: Box

    @property
    def center(self) -> tuple[float, float]:
        return self.box.center

    def text(self) -> str:
        return " | ".join(f"{k}={v}" for k, v in self.cells.items())


@dataclass(frozen=True)
class Grid:
    columns: tuple[str, ...]
    header: Box
    rows: tuple[GridRow, ...]

    def values(self, column: str) -> list[str]:
        return [r.cells.get(column, "") for r in self.rows]

    def signature(self) -> tuple[tuple[str, ...], ...]:
        return tuple(tuple(r.cells.get(c, "") for c in self.columns) for r in self.rows)


def visual_rows(words: Iterable[OcrWord]) -> list[list[OcrWord]]:
    ordered = sorted(words, key=lambda w: w.box.center[1])
    if not ordered:
        return []
    tolerance = 0.6 * median(w.box.height for w in ordered)
    rows: list[list[OcrWord]] = []
    for word in ordered:
        if rows and abs(word.box.center[1] - median(w.box.center[1] for w in rows[-1])) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(r, key=lambda w: w.box.left) for r in rows]


def match_headers(row: list[OcrWord], columns: tuple[str, ...]) -> dict[str, Box]:
    found: dict[str, Box] = {}
    position = 0
    for column in columns:
        target = header_key(column)
        hit = None
        for start in range(position, len(row)):
            joined = ""
            for end in range(start, min(start + MAX_HEADER_WORDS, len(row))):
                joined += header_key(row[end].text)
                if joined == target:
                    hit = (start, end)
                    break
                if not target.startswith(joined):
                    break
            if hit:
                break
        if target and hit:
            found[column] = Box.union(w.box for w in row[hit[0]:hit[1] + 1])
            position = hit[1] + 1
    return found


def _header_row(rows: list[list[OcrWord]], columns: tuple[str, ...]) -> tuple[int, dict[str, Box]]:
    best_index, best = -1, {}
    for index, row in enumerate(rows):
        found = match_headers(row, columns)
        if len(found) > len(best):
            best_index, best = index, found
    return best_index, best


def parse_grid(words: Iterable[OcrWord], columns: Iterable[str], *, required: Iterable[str] | None = None) -> Grid:
    columns = tuple(columns)
    required = tuple(required) if required is not None else columns
    rows = visual_rows(w for w in words if not GRID_LINE_NOISE.fullmatch(w.text))
    index, headers = _header_row(rows, columns)
    missing = [c for c in required if c not in headers]
    if index < 0 or missing:
        seen = [" ".join(w.text for w in r) for r in rows[:3]]
        raise ControlNotFound(f"table header not found: missing {missing or list(columns)}; OCR saw {seen}")

    found = sorted(headers.items(), key=lambda kv: kv[1].left)
    names = tuple(name for name, _ in found)
    starts = [box.left - HEADER_PAD for _, box in found]
    header_box = Box.union(box for _, box in found)

    def column_of(word: OcrWord) -> str | None:
        x = word.box.center[0]
        for i in range(len(starts) - 1, -1, -1):
            if x >= starts[i]:
                return names[i]
        return None

    grid_rows = []
    for row in rows[index + 1:]:
        if min(w.box.top for w in row) < header_box.bottom:
            continue
        cells: dict[str, list[str]] = {name: [] for name in names}
        placed = []
        for word in row:
            name = column_of(word)
            if name is not None:
                cells[name].append(word.text)
                placed.append(word)
        if placed:
            grid_rows.append(GridRow({k: " ".join(v) for k, v in cells.items()}, Box.union(w.box for w in placed)))
    return Grid(names, header_box, tuple(grid_rows))


def find_rows(grid: Grid, expected: dict[str, str]) -> list[tuple[GridRow, dict[str, str]]]:
    hits = []
    for row in grid.rows:
        how = {c: cell_matches(row.cells.get(c, ""), v) for c, v in expected.items()}
        if all(how.values()):
            hits.append((row, how))
    return hits


def overlaps(a: Box, b: Box, threshold: float = 0.5) -> bool:
    left, top = max(a.left, b.left), max(a.top, b.top)
    right, bottom = min(a.right, b.right), min(a.bottom, b.bottom)
    if right <= left or bottom <= top:
        return False
    inter = (right - left) * (bottom - top)
    return inter >= threshold * min(a.width * a.height, b.width * b.height)


def merge_words(primary: list[OcrWord], extra: list[OcrWord]) -> list[OcrWord]:
    merged = list(primary)
    for word in extra:
        if not any(overlaps(word.box, kept.box) for kept in merged):
            merged.append(word)
    return merged


def ocr_words(image: Any, *, scale: float = 2.0, lang: str = "en") -> list[OcrWord]:
    from PIL import ImageOps

    from image_to_cash.ocr import run_ocr

    def words_of(img: Any) -> list[OcrWord]:
        return [w for line in run_ocr(img, lang=lang, scale=scale).lines for w in line.words]

    plain = words_of(image)
    inverted = words_of(ImageOps.invert(image.convert("L")).convert("RGB"))
    return merge_words(plain, inverted)


def capture_words(node: Any, *, scale: float = 2.0, lang: str = "en") -> tuple[list[OcrWord], Any]:
    rect = node.rect
    image = node.wrapper().capture_as_image()
    left, top = rect[0], rect[1]
    words = [
        OcrWord(w.text, Box(w.box.left + left, w.box.top + top, w.box.width, w.box.height))
        for w in ocr_words(image, scale=scale, lang=lang)
    ]
    return words, image


def read_grid(node: Any, columns: Iterable[str], *, required: Iterable[str] | None = None,
              scale: float = 2.0, lang: str = "en") -> Grid:
    words, _ = capture_words(node, scale=scale, lang=lang)
    return parse_grid(words, columns, required=required)


def click_row(row: GridRow, *, double: bool = False) -> None:
    from pywinauto import mouse

    x, y = (int(round(v)) for v in row.center)
    if double:
        mouse.double_click(coords=(x, y))
    else:
        mouse.click(coords=(x, y))
