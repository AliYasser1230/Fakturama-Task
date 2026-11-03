from image_to_cash.extract.crosscheck import critical_values, crosscheck, fold


def test_all_values_present_gives_no_issues(raw, sample_ocr_text):
    assert crosscheck(raw, sample_ocr_text) == []


def test_invented_value_is_caught(raw, sample_ocr_text):
    raw.items[0].sku = "CHR-ERG-07"  # not on the image
    issues = crosscheck(raw, sample_ocr_text)
    assert [i.field for i in issues] == ["items[0].sku"]
    assert issues[0].level == "error"


def test_spacing_case_and_lookalikes_are_tolerated(raw):
    # OCR read "O" for "0", "l" for "1", and split tokens differently.
    ocr = (
        "WEB-2O26-O7l4-Al7\n" + "\n".join(v for p, v in critical_values(raw) if p != "order.external_reference")
    ).replace("EUR 570.00", "EUR570.00")
    assert crosscheck(raw, ocr) == []


def test_fold():
    assert fold("  Web 2026-0714 ") == fold("WEB2O26-O7l4") == "web2026-0714"


def test_critical_values_cover_items_and_totals(raw):
    paths = {p for p, _ in critical_values(raw)}
    assert {"items[1].sku", "items[1].line_net", "totals.gross_total", "delivery_address.zip"} <= paths
    # Empty values (salutation, district, ...) are not checked.
    assert not any(p.endswith(".salutation") or p.endswith(".district") for p in paths)
