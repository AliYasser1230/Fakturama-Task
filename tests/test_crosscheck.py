from image_to_cash.extract.crosscheck import critical_values, crosscheck, fold, spellings


def _ocr_without(raw, *paths):
    return "\n".join(v for p, v in critical_values(raw) if p not in paths)


def _levels(issues):
    return [(i.level, i.field) for i in issues]


def test_all_values_present_gives_no_issues(raw, sample_ocr_text):
    assert crosscheck(raw, sample_ocr_text) == []


def test_invented_value_is_caught(raw, sample_ocr_text):
    raw.items[0].sku = "CHR-ERG-07"
    issues = crosscheck(raw, sample_ocr_text)
    assert [i.field for i in issues] == ["items[0].sku"]
    assert issues[0].level == "error"


def test_spacing_case_and_lookalikes_are_tolerated(raw):
    ocr = (
        "WEB-2O26-O7l4-Al7\n" + "\n".join(v for p, v in critical_values(raw) if p != "order.external_reference")
    ).replace("EUR 570.00", "EUR570.00")
    assert crosscheck(raw, ocr) == []


def test_fold():
    assert fold("  Web 2026-0714 ") == fold("WEB2O26-O7l4") == "web2026-0714"


def test_critical_values_cover_items_and_totals(raw):
    paths = {p for p, _ in critical_values(raw)}
    assert {"items[1].sku", "items[1].line_net", "totals.gross_total", "delivery_address.zip"} <= paths
    assert not any(p.endswith(".salutation") or p.endswith(".district") for p in paths)


def test_percent_spellings():
    assert spellings("10%") == {"10%", "1096", "100/0"}
    assert spellings("EUR 570.00") == {"eur570.00"}


def test_windows_ocr_misreadings_of_percent_count_as_found(raw):
    text = _ocr_without(raw, "items[0].discount", "items[1].discount")
    assert crosscheck(raw, text + "\n1096\n00/0") == []
    assert crosscheck(raw, text + "\n100/0\n00/0") == []


def test_missing_discount_is_a_warning_when_ocr_found_the_line_amounts(raw):
    issues = crosscheck(raw, _ocr_without(raw, "items[0].discount", "items[1].discount"))
    assert _levels(issues) == [("warning", "items[0].discount"), ("warning", "items[1].discount")]
    assert "step D" in issues[0].message


def test_missing_discount_is_an_error_when_its_line_net_is_missing_too(raw):
    issues = crosscheck(raw, _ocr_without(raw, "items[0].discount", "items[0].line_net"))
    assert _levels(issues) == [("error", "items[0].discount"), ("error", "items[0].line_net")]


def test_missing_vat_rate_is_a_warning_only_when_every_line_has_that_rate(raw):
    text = _ocr_without(raw, "items[0].vat", "items[1].vat")
    assert _levels(crosscheck(raw, text)) == [("warning", "items[0].vat"), ("warning", "items[1].vat")]

    raw.items[1].vat = "7%"
    assert _levels(crosscheck(raw, text)) == [("error", "items[0].vat"), ("error", "items[1].vat")]


def test_missing_vat_rate_is_an_error_when_the_vat_total_is_missing_too(raw):
    issues = crosscheck(raw, _ocr_without(raw, "items[0].vat", "items[1].vat", "totals.vat_total"))
    assert {i.level for i in issues} == {"error"}


def test_non_percent_values_never_fall_back(raw):
    issues = crosscheck(raw, _ocr_without(raw, "items[0].unit_net_price"))
    assert _levels(issues) == [("error", "items[0].unit_net_price")]
