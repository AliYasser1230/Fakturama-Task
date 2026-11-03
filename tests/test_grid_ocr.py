import json
from pathlib import Path

import pytest

from image_to_cash.errors import ControlNotFound
from image_to_cash.ocr import Box, OcrWord
from image_to_cash.ui.grid_ocr import cell_matches, find_rows, parse_grid, visual_rows

FIXTURES = Path(__file__).parent / "fixtures" / "ocr"
ADDRESS_COLUMNS = ("No.", "First Name", "Name", "Company", "ZIP", "City")


def _captured(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return [OcrWord(w["text"], Box(*w["box"])) for w in data["words"]]


def W(text, left, top, width=None, height=10):
    return OcrWord(text, Box(left, top, width or 6 * len(text), height))


def _address_table(*rows):
    words = [W("No.", 30, 5), W("First", 100, 5), W("Name", 133, 5), W("Name", 200, 4),
             W("Company", 300, 5), W("ZIP", 450, 5), W("City", 520, 5)]
    for i, (no, first, last, company, zip_code, city) in enumerate(rows, start=1):
        y = 5 + 20 * i
        words += [W(str(i), 8, y), W(no, 30, y), W(first, 100, y), W(last, 200, y + 1)]
        words += [W(part, 300 + 50 * k, y) for k, part in enumerate(company.split())]
        words += [W(zip_code, 450, y), W(city, 520, y)]
    return words


def test_real_vat_list_capture():
    grid = parse_grid(_captured("vats_list_table"), ["Standard", "Name", "Description", "Value"])
    assert grid.columns == ("Standard", "Name", "Description", "Value")
    assert [r.cells for r in grid.rows] == [
        {"Standard": "", "Name": "Tax-free", "Description": "Free of Tax", "Value": "0.00 %"}]


def test_real_empty_documents_list_capture():
    columns = ["Document", "Date", "Name", "Cust.Ref.", "State", "Total", "Printed"]
    grid = parse_grid(_captured("documents_list_table"), columns)
    assert grid.columns == tuple(columns) and grid.rows == ()


def test_duplicate_header_words_go_to_the_right_columns():
    grid = parse_grid(_address_table(
        ("CUST000001", "Marta", "Klein", "Northstar Office GmbH", "10117", "Berlin"),
        ("CUST000002", "Jan", "Klein", "Other GmbH", "80331", "Munich"),
    ), ADDRESS_COLUMNS)
    assert grid.values("First Name") == ["Marta", "Jan"]
    assert grid.values("Name") == ["Klein", "Klein"]
    assert grid.values("Company") == ["Northstar Office GmbH", "Other GmbH"]
    assert grid.values("ZIP") == ["10117", "80331"]


def test_row_numbers_left_of_the_first_column_are_ignored():
    grid = parse_grid(_address_table(("CUST000001", "Marta", "Klein", "A", "1", "B")), ADDRESS_COLUMNS)
    assert grid.rows[0].cells["No."] == "CUST000001"


def test_find_rows_exact_lookalike_and_truncated():
    grid = parse_grid(_address_table(
        ("CUST000001", "Marta", "Klein", "Northstar Offic...", "1O117", "Berlin"),
        ("CUST000002", "Marta", "Klein", "Northstar Labs", "10117", "Berlin"),
    ), ADDRESS_COLUMNS)
    wanted = {"Company": "Northstar Office GmbH", "First Name": "Marta", "Name": "Klein", "ZIP": "10117", "City": "Berlin"}
    hits = find_rows(grid, wanted)
    assert len(hits) == 1
    row, how = hits[0]
    assert row.cells["No."] == "CUST000001"
    assert how["Company"] == "truncated" and how["ZIP"] == "exact"


@pytest.mark.parametrize("shown, expected, result", [
    ("CHR-ERG-OI", "CHR-ERG-01", "exact"),
    ("Northstar Office GmbH", "Northstar Office GmbH", "exact"),
    ("Northstar Off…", "Northstar Office GmbH", "truncated"),
    ("Northstar Off...", "Other GmbH", None),
    ("...", "Anything", None),
    ("Northstar", "Northstar Office GmbH", None),
])
def test_cell_matches(shown, expected, result):
    assert cell_matches(shown, expected) == result


def test_header_is_found_below_other_text():
    words = [W("Search:", 400, 0)] + [OcrWord(w.text, Box(w.box.left, w.box.top + 30, w.box.width, w.box.height))
                                       for w in _address_table(("C1", "Marta", "Klein", "A", "1", "B"))]
    grid = parse_grid(words, ADDRESS_COLUMNS)
    assert len(grid.rows) == 1 and grid.rows[0].cells["First Name"] == "Marta"


def test_missing_header_is_an_error_naming_what_ocr_saw():
    words = [W("Document", 10, 5), W("Date", 100, 5)]
    with pytest.raises(ControlNotFound, match=r"missing \['Total'\].*Document Date"):
        parse_grid(words, ["Document", "Date", "Total"])
    grid = parse_grid(words, ["Document", "Date", "Total"], required=["Document"])
    assert grid.columns == ("Document", "Date")


def test_visual_rows_group_words_with_small_vertical_offsets():
    rows = visual_rows([W("a", 0, 10), W("b", 50, 12), W("c", 0, 30), W("d", 50, 29)])
    assert [[w.text for w in r] for r in rows] == [["a", "b"], ["c", "d"]]


def test_signature_changes_when_rows_change():
    one = parse_grid(_address_table(("C1", "Marta", "Klein", "A", "1", "B")), ADDRESS_COLUMNS)
    two = parse_grid(_address_table(("C1", "Marta", "Klein", "A", "1", "B"), ("C2", "Jan", "X", "Y", "2", "Z")), ADDRESS_COLUMNS)
    assert one.signature() != two.signature()
    assert one.signature() == parse_grid(_address_table(("C1", "Marta", "Klein", "A", "1", "B")), ADDRESS_COLUMNS).signature()


def test_column_lines_read_as_letters_are_dropped():
    words = _address_table(("CUST000001", "Marta", "Klein", "Northstar", "10117", "Berlin"))
    words += [W("II", 95, 25, width=4), W("I", 195, 25, width=2), W("|", 445, 25, width=2)]
    grid = parse_grid(words, ADDRESS_COLUMNS)
    assert grid.rows[0].cells["No."] == "CUST000001"
    assert grid.rows[0].cells["First Name"] == "Marta" and grid.rows[0].cells["ZIP"] == "10117"


def test_a_real_quantity_of_one_is_kept():
    words = [W("Pos.", 10, 5), W("Qty.", 60, 5), W("1", 12, 25), W("1", 62, 25)]
    grid = parse_grid(words, ["Pos.", "Qty."])
    assert grid.rows[0].cells == {"Pos.": "1", "Qty.": "1"}


def test_inverted_pass_only_adds_words_that_are_new():
    from image_to_cash.ui.grid_ocr import merge_words

    plain = [W("Tax-free", 100, 25)]
    inverted = [W("Tax-free", 101, 25), W("Free", 200, 25)]
    assert [w.text for w in merge_words(plain, inverted)] == ["Tax-free", "Free"]
