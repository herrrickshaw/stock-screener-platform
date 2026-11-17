"""Unit tests for parsers/excel_parser.py with synthetic in-memory workbooks.

The instrument master is replaced by a tiny synthetic India table injected into
market_db's cache, so no data file, DuckDB or network is touched."""
import io
from datetime import datetime

import openpyxl
import pytest

from parsers import excel_parser, market_db

SYMS = {"RELIANCE": "Reliance Industries Ltd", "BAJAJ-AUTO": "Bajaj Auto Ltd",
        "TCS": "Tata Consultancy Services Ltd"}


@pytest.fixture(autouse=True)
def fake_india_master(monkeypatch):
    db = {"by_yf": {f"{s}.NS": {"yf_ticker": f"{s}.NS", "name": n, "code": s} for s, n in SYMS.items()},
          "by_code": {s: f"{s}.NS" for s in SYMS},
          "by_name": {n.lower(): f"{s}.NS" for s, n in SYMS.items()}}
    monkeypatch.setitem(market_db._CACHE, "india", db)


def _xlsx(rows, preamble=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Holdings"
    for r in preamble:
        ws.append(r)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _by_ticker(res):
    return {s["yf_ticker"]: s for s in res["stocks"]}


def test_header_detection_and_holding_fields():
    data = _xlsx([["Symbol", "Qty", "Avg Price", "Buy Date"],
                  ["RELIANCE-EQ", "10", "₹2,450.50", datetime(2024, 3, 15)],
                  ["TCS", 5, 3500, "15/03/2024"]],
                 preamble=[["Client statement"], []])
    s = _by_ticker(excel_parser.parse_excel(data, "india"))
    assert s["RELIANCE.NS"]["quantity"] == 10.0
    assert s["RELIANCE.NS"]["purchase_price"] == 2450.5
    assert s["RELIANCE.NS"]["purchase_date"] == "2024-03-15"
    assert s["RELIANCE.NS"]["matched_via"] == "symbol"
    assert s["TCS.NS"]["purchase_date"] == "2024-03-15"


def test_hyphenated_nse_symbol_resolves_by_symbol():
    """BAJAJ-AUTO is a real NSE symbol; stripping at the first '-' (meant for '-EQ')
    reduced it to 'BAJAJ' and lost the symbol match."""
    s = _by_ticker(excel_parser.parse_excel(_xlsx([["Symbol"], ["BAJAJ-AUTO"]]), "india"))
    assert "BAJAJ-AUTO.NS" in s
    assert s["BAJAJ-AUTO.NS"]["matched_via"] == "symbol"


def test_name_only_rows_fall_back_to_name_match():
    s = _by_ticker(excel_parser.parse_excel(_xlsx([["Company Name"], ["Tata Consultancy Services"]]),
                                            "india"))
    assert s["TCS.NS"]["matched_via"] == "name (fuzzy)"


def test_unresolved_rows_produce_a_warning():
    res = excel_parser.parse_excel(_xlsx([["Company Name"], ["Zzzz Nonexistent Qqq"]]), "india")
    assert res["stocks"] == []
    assert "could not be matched" in res["warnings"][0]


@pytest.mark.xfail(strict=True, reason="rows are de-duplicated by ticker, so a second lot "
                                       "(different date/qty) of the same stock is dropped")
def test_two_lots_of_one_stock_are_both_kept():
    res = excel_parser.parse_excel(_xlsx([["Symbol", "Qty", "Buy Date"],
                                          ["TCS", 10, "2024-01-02"], ["TCS", 5, "2024-06-03"]]),
                                   "india")
    assert sum(s.get("quantity", 0) for s in res["stocks"]) == 15


@pytest.mark.parametrize("raw,val", [("1,234.50", 1234.5), ("$12", 12.0), ("abc", None), ("", None)])
def test_parse_float(raw, val):
    assert excel_parser._parse_float(raw) == val


def test_pdf_table_hyphenated_symbol_resolves_by_symbol():
    from parsers import pdf_parser
    rows = pdf_parser._parse_table([["Symbol", "Qty"], ["BAJAJ-AUTO", "3"], ["RELIANCE-EQ", "1"]],
                                   "page 1", "india")
    assert {r["yf_ticker"]: r["matched_via"] for r in rows} == {
        "BAJAJ-AUTO.NS": "symbol", "RELIANCE.NS": "symbol"}
