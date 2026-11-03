from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Callable, Iterable

from image_to_cash.errors import ControlNotFound
from image_to_cash.extract.crosscheck import fold
from image_to_cash.ocr import Box, OcrWord

HEADER_PAD = 4.0
MAX_HEADER_WORDS = 4
GRID_LINE_NOISE = re.compile(r"[Il|!]+")
LINE_MARGIN = 3
LINE_COVERAGE = 0.9
LINE_CONTRAST = 20


def header_key(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", fold(text))


def cell_key(text: str) -> str:
    return fold(text)


TRAILING_DOTS = re.compile(r"[\s.\u2022\u00b7\u2026]+$")
MIN_STEM = 3


def cut_off_stem(shown: str) -> str | None:
    m = TRAILING_DOTS.search(shown)
    if not m:
        return None
    tail = m.group()
    if sum(ch in ".\u2022\u00b7" for ch in tail) < 2 and "\u2026" not in tail and "\u2022" not in tail:
        return None
    return shown[: m.start()]


def cell_matches(shown: str, expected: str) -> str | None:
    shown = " ".join((shown or "").split())
    expected = " ".join((expected or "").split())
    if cell_key(shown) == cell_key(expected):
        return "exact"
    stem = cut_off_stem(shown)
    if stem is not None and len(cell_key(stem)) >= MIN_STEM and cell_key(expected).startswith(cell_key(stem)):
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


def column_lines(image: Any, header: Box, *, offset: tuple[float, float] = (0.0, 0.0)) -> list[float]:
    gray = image.convert("L")
    px = gray.load()
    width, height = gray.size
    left, top = offset
    y0 = max(0, int(header.top - top) - LINE_MARGIN)
    y1 = min(height, int(header.bottom - top) + LINE_MARGIN + 1)
    if y1 - y0 < 4:
        return []
    band = [[px[x, y] for y in range(y0, y1)] for x in range(width)]
    background = median(v for column in band for v in column)
    dark = [x for x in range(width)
            if sum(1 for v in band[x] if v < background - LINE_CONTRAST) >= LINE_COVERAGE * (y1 - y0)]
    groups: list[list[int]] = []
    for x in dark:
        if groups and x - groups[-1][-1] <= 2:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [left + sum(g) / len(g) for g in groups]


def column_spans(headers: list[tuple[str, Box]], lines: list[float]) -> list[tuple[str, float, float]] | None:
    spans = []
    for name, box in headers:
        center = box.center[0]
        left = max((x for x in lines if x < center), default=float("-inf"))
        right = min((x for x in lines if x > center), default=float("inf"))
        spans.append((name, left, right))
    edges = [(left, right) for _, left, right in spans]
    if len(set(edges)) != len(edges):
        return None
    return spans


def parse_grid(words: Iterable[OcrWord], columns: Iterable[str], *, required: Iterable[str] | None = None,
               line_finder: Callable[[Box], list[float]] | None = None) -> Grid:
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
    spans = column_spans(found, line_finder(header_box)) if line_finder is not None else None

    def column_of(word: OcrWord) -> str | None:
        x = word.box.center[0]
        if spans is not None:
            return next((name for name, left, right in spans if left < x < right), None)
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


HEADER_BAND = 24
HEADER_SCALE = 3.0


def ocr_words(image: Any, *, scale: float = 2.0, lang: str = "en") -> list[OcrWord]:
    from PIL import ImageOps

    from image_to_cash.ocr import run_ocr

    def words_of(img: Any, at: float = scale) -> list[OcrWord]:
        return [w for line in run_ocr(img, lang=lang, scale=at).lines for w in line.words]

    plain = words_of(image)
    inverted = words_of(ImageOps.invert(image.convert("L")).convert("RGB"))
    band = image.crop((0, 0, image.width, min(HEADER_BAND, image.height)))
    header = words_of(ImageOps.autocontrast(band.convert("L"), cutoff=2).convert("RGB"), HEADER_SCALE)
    return merge_words(merge_words(plain, inverted), header)


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
    words, image = capture_words(node, scale=scale, lang=lang)
    offset = (node.rect[0], node.rect[1])
    return parse_grid(words, columns, required=required,
                      line_finder=lambda header: column_lines(image, header, offset=offset))


def click_row(row: GridRow, *, double: bool = False) -> None:
    from pywinauto import mouse

    x, y = (int(round(v)) for v in row.center)
    if double:
        mouse.double_click(coords=(x, y))
    else:
        mouse.click(coords=(x, y))


CELL_PAD = 12


def has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def line_row(rows: list[list[OcrWord]], key: str) -> list[OcrWord] | None:
    hits = [r for r in rows if any(cell_key(w.text) == cell_key(key) for w in r)]
    return hits[0] if len(hits) == 1 else None


def row_at(rows: list[list[OcrWord]], y: float, tolerance: float = 6.0) -> list[OcrWord] | None:
    near = [r for r in rows if abs(median(w.box.center[1] for w in r) - y) <= tolerance]
    return near[0] if len(near) == 1 else None


def cell_word(rows: list[list[OcrWord]], row: list[OcrWord], column: str, key: str | None = None,
              left_of_key: bool = False) -> OcrWord | None:
    if left_of_key:
        anchor = next((w for w in row if cell_key(w.text) == cell_key(key or "")), None)
        if anchor is None:
            return None
        before = [w for w in row if w.box.right <= anchor.box.left + 1 and has_digit(w.text)]
        return before[-1] if before else None
    header = rows[0]
    found = match_headers(header, (column,))
    if column not in found:
        return None
    box = found[column]
    following = [w.box.left for w in header if w.box.left > box.right + 2]
    right = min(following) - 4 if following else float("inf")
    cells = [w for w in row if box.left - CELL_PAD <= w.box.center[0] < right and has_digit(w.text)]
    return cells[0] if cells else None
