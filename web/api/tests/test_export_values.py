import csv
import io
import json
import xml.etree.ElementTree as ET

from tradingagents_api.export_values import csv_cell, export_row, finite, xml_text


def test_loss_aware_export_values_preserve_valid_numbers_and_source_record():
    raw = {"price": True, "pe_ttm": "8", "volume": float("inf"), "new_high": 2, "market_cap": 0}
    result = export_row(raw, list(raw))
    assert result["market_cap"] == 0
    assert all(result[k] == "Unavailable" for k in ["price", "pe_ttm", "volume", "new_high"])
    assert len(result["export_value_issues"]) == 4
    assert raw["price"] is True
    encoded = csv_cell(result["export_value_issues"])
    issues = json.loads(next(csv.reader([encoded]))[0])
    assert issues[2]["source_value"] == {
        "export_unavailable": "nonfinite_number",
        "source_value": "inf",
    }
    assert not finite(10**400)
    assert json.loads(next(csv.reader([csv_cell(float("nan"))]))[0])["source_value"] == "nan"


def test_csv_formula_guard_and_xml_control_preservation():
    for value in ["=1+1", "  +SUM(A1)", "\tplain", "\r=1+1", "\nplain", " -2"]:
        assert next(csv.reader(io.StringIO(csv_cell(value))))[0] == "'" + value
    assert csv_cell(-2) == "-2"
    text = xml_text({"value": float("inf"), "note": "a\x01<&"})
    root = ET.fromstring("<value>" + text + "</value>")
    decoded = json.loads(root.text)
    assert decoded["value"]["export_unavailable"] == "nonfinite_number"
    assert decoded["note"] == "a\x01<&"
    assert ET.fromstring("<value>" + xml_text("a\x01<&") + "</value>").text == "a\\u0001<&"
