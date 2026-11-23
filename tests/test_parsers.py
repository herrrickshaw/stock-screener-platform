"""Offline tests for backend.parsers: NSE symbol DB, multi-market symbol DB, Excel holdings parser.

All symbol lists are written to tmp_path; module-level caches are replaced via monkeypatch so no
repository data file (several are git-ignored) is read.
"""
import datetime as dt
import io

import openpyxl
import pytest

from parsers import excel_parser as xp
from parsers import market_db as mdb
from parsers import symbol_db as sdb

NSE_CSV = """SYMBOL,NAME OF COMPANY,ISIN NUMBER
TCS,Tata Consultancy Services Limited,INE467B01029
INFY,Infosys Limited,INE009A01021
M&M,Mahindra & Mahindra Limited,INE101A01026
,No Symbol Co,INE000000000
NOISIN,No Isin Limited,
NONAME,,INE111111111
"""


@pytest.fixture
def nse(tmp_path, monkeypatch):
    path = tmp_path / "nse.csv"
    path.write_text(NSE_CSV, encoding="utf-8")
    monkeypatch.setattr(sdb, "_CSV", str(path))
    for name, empty in (("_BY_SYMBOL", {}), ("_BY_ISIN", {}), ("_BY_NAME", {}), ("_ALL_NAMES", [])):
        monkeypatch.setattr(sdb, name, empty)
    monkeypatch.setattr(mdb, "_CACHE", {})
    return path


# ------------------------------------------------------------------ symbol_db
def test_load_skips_rows_without_symbol_and_indexes_the_rest(nse):
    sdb._load()
    assert set(sdb._BY_SYMBOL) == {"TCS", "INFY", "M&M", "NOISIN", "NONAME"}
    assert sdb._BY_ISIN["INE467B01029"] == "TCS"
    assert "NOISIN" not in sdb._BY_ISIN.values()
    assert "" not in sdb._BY_NAME and sdb._BY_NAME["infosys limited"] == "INFY"
    assert len(sdb._ALL_NAMES) == 4                          # NONAME has no name


def test_load_is_idempotent(nse):
    sdb._load()
    sdb._load()
    assert len(sdb._ALL_NAMES) == 4


def test_load_missing_file_is_a_silent_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(sdb, "_CSV", str(tmp_path / "absent.csv"))
    monkeypatch.setattr(sdb, "_BY_SYMBOL", {})
    sdb._load()
    assert sdb.lookup_by_symbol("TCS") is None


def test_lookup_by_symbol_normalises_case_and_space(nse):
    assert sdb.lookup_by_symbol("  tcs ")["name"] == "Tata Consultancy Services Limited"
    assert sdb.lookup_by_symbol("m&m")["symbol"] == "M&M"
    assert sdb.lookup_by_symbol("NOPE") is None


def test_lookup_by_isin(nse):
    assert sdb.lookup_by_isin(" INE009A01021 ")["symbol"] == "INFY"
    assert sdb.lookup_by_isin("INE000000000") is None
    assert sdb.lookup_by_isin("") is None


def test_lookup_by_name_exact_then_fuzzy_with_cutoff(nse):
    assert sdb.lookup_by_name("INFOSYS LIMITED")["symbol"] == "INFY"            # exact, case-insensitive
    assert sdb.lookup_by_name("Infosys Ltd")["symbol"] == "INFY"                 # fuzzy
    assert sdb.lookup_by_name("Zebra Quartz Mining") is None
    assert sdb.lookup_by_name("Infosys Ltd", cutoff=0.99) is None


def test_is_valid_nse_symbol(nse):
    assert sdb.is_valid_nse_symbol("tcs") and sdb.is_valid_nse_symbol(" INFY ")
    assert not sdb.is_valid_nse_symbol("ZZZ")


def test_extract_symbols_prefers_isin_then_adds_symbol_mentions(nse):
    text = "Holding INE467B01029 and also INFY plus ABCDE and TCS again"
    out = sdb.extract_symbols_from_text(text)
    by_sym = {o["symbol"]: o for o in out}
    assert set(by_sym) == {"TCS", "INFY"}
    assert by_sym["TCS"]["matched_via"] == "ISIN" and by_sym["TCS"]["raw"] == "INE467B01029"
    assert by_sym["INFY"]["matched_via"] == "symbol"
    assert len(out) == 2                                     # TCS not duplicated by the symbol pass


def test_extract_symbols_unknown_isin_and_empty_text(nse):
    assert sdb.extract_symbols_from_text("INE999Z99Z99 nothing") == []
    assert sdb.extract_symbols_from_text("") == []


# ------------------------------------------------------------------ market_db
@pytest.fixture
def mkt(tmp_path, monkeypatch, nse):
    monkeypatch.setattr(mdb, "_DATA", str(tmp_path))
    (tmp_path / "japan_list.csv").write_text(
        "yf_ticker,name,symbol\n7203.T,Toyota Motor,7203\n6758.T,Sony Group,6758\n,Blank,0000\n")
    (tmp_path / "us_list.csv").write_text(
        "yf_ticker,name,symbol,exchange\nAAPL,Apple Inc,AAPL,NASDAQ\nMSFT,Microsoft Corp,MSFT,NASDAQ\n")
    (tmp_path / "europe_all_list.csv").write_text(
        "yf_ticker,name,exchange,index\nADS.DE,Adidas AG,XETRA,DAX\nRIO.L,Rio Tinto,LSE,FTSE\n")
    (tmp_path / "china_list.csv").write_text(
        "yf_ticker,name,symbol,exchange\n600519.SS,Kweichow Moutai,600519,SSE\n000001.SZ,Ping An Bank,000001,SZSE\n")
    return tmp_path


def test_load_csv_builds_three_indexes_and_extra_columns(mkt):
    db = mdb._load_csv(str(mkt / "us_list.csv"), "yf_ticker", "name", "symbol", ["exchange"])
    assert db["by_yf"]["AAPL"] == {"yf_ticker": "AAPL", "name": "Apple Inc", "code": "AAPL", "exchange": "NASDAQ"}
    assert db["by_code"] == {"AAPL": "AAPL", "MSFT": "MSFT"}
    assert db["by_name"]["microsoft corp"] == "MSFT"


def test_load_csv_skips_rows_without_ticker_and_tolerates_missing_file(mkt):
    db = mdb._load_csv(str(mkt / "japan_list.csv"), "yf_ticker", "name", "symbol")
    assert set(db["by_yf"]) == {"7203.T", "6758.T"}
    assert mdb._load_csv(str(mkt / "nope.csv"), "a", "b") == {"by_yf": {}, "by_code": {}, "by_name": {}}


def test_db_is_cached_per_market_and_unknown_market_is_empty(mkt):
    assert mdb.db_size("japan") == 2
    (mkt / "japan_list.csv").write_text("yf_ticker,name,symbol\n")
    assert mdb.db_size("japan") == 2                         # cached, file change ignored
    assert mdb.db_size("atlantis") == 0


def test_db_india_is_derived_from_nse_symbol_db(mkt):
    db = mdb._db("india")
    assert db["by_yf"]["TCS"] == {"yf_ticker": "TCS.NS", "name": "Tata Consultancy Services Limited", "code": "TCS"}
    assert db["by_code"]["INFY"] == "INFY.NS" and db["by_name"]["infosys limited"] == "INFY.NS"


def test_db_europe_falls_back_to_legacy_list_when_new_one_missing(mkt, monkeypatch):
    (mkt / "europe_all_list.csv").unlink()
    (mkt / "europe_list.csv").write_text("yf_ticker,name,exchange,index\nSAP.DE,SAP SE,XETRA,DAX\n")
    assert list(mdb._db("europe")["by_yf"]) == ["SAP.DE"]


def test_db_us_falls_back_to_sp500_list(mkt):
    (mkt / "us_list.csv").unlink()
    (mkt / "sp500_list.csv").write_text("Symbol,Security,GICS Sector\nKO,Coca-Cola,Staples\n")
    db = mdb._db("us")
    assert db["by_yf"]["KO"]["name"] == "Coca-Cola" and db["by_yf"]["KO"]["GICS Sector"] == "Staples"


def test_lookup_direct_yf_ticker_code_and_suffix_forms(mkt):
    assert mdb.lookup("7203.T", "japan")["name"] == "Toyota Motor"        # direct
    assert mdb.lookup("7203", "japan")["yf_ticker"] == "7203.T"           # by code
    assert mdb.lookup(" 6758 ", "japan")["name"] == "Sony Group"          # stripped
    assert mdb.lookup("ADS.DE", "europe")["name"] == "Adidas AG"
    assert mdb.lookup("0000", "japan") is None
    assert mdb.lookup("TCS", "india")["yf_ticker"] == "TCS.NS"
    assert mdb.lookup("ZZZ", "india") is None


def test_lookup_appends_market_suffix_when_code_index_misses(mkt):
    # europe has no code column; 'RIO' + '' suffix -> no match, but japan suffix path works for yf-only rows
    (mkt / "korea_list.csv").write_text("yf_ticker,name,symbol,market\n005930.KS,Samsung,,KOSPI\n")
    assert mdb.lookup("005930", "korea")["name"] == "Samsung"
    assert mdb.lookup("RIO", "europe") is None


def test_lookup_china_tries_ss_then_sz(mkt):
    assert mdb.lookup("600519", "china")["name"] == "Kweichow Moutai"
    assert mdb.lookup("000001", "china")["name"] == "Ping An Bank"
    assert mdb.lookup("999999", "china") is None


def test_lookup_by_name_exact_fuzzy_and_miss(mkt):
    assert mdb.lookup_by_name("toyota motor", "japan")["yf_ticker"] == "7203.T"
    assert mdb.lookup_by_name("Toyota Motors", "japan")["yf_ticker"] == "7203.T"
    assert mdb.lookup_by_name("qqqqqqqqqqqq", "japan") is None
    assert mdb.lookup_by_name("anything", "atlantis") is None


def test_extract_from_text_matches_isin_first_for_india(mkt):
    out = mdb.extract_from_text("ISIN INE467B01029 and INFY", "india")
    by = {o["yf_ticker"]: o for o in out}
    assert set(by) == {"TCS.NS", "INFY.NS"}
    assert by["TCS.NS"]["matched_via"] == "ISIN" and by["TCS.NS"]["raw"] == "INE467B01029"
    assert by["INFY.NS"]["matched_via"] == "symbol"


def test_extract_from_text_ignores_isins_of_other_countries(mkt):
    assert mdb.extract_from_text("US0378331005", "india") == []


def test_extract_from_text_japan_codes_and_dedup(mkt):
    out = mdb.extract_from_text("buy 7203 and 7203.T and 6758 plus 1111", "japan")
    assert sorted(o["yf_ticker"] for o in out) == ["6758.T", "7203.T"]


def test_extract_from_text_unknown_market_returns_empty(mkt):
    assert mdb.extract_from_text("AAPL", "atlantis") == []


def test_market_tables_cover_the_same_markets():
    assert set(mdb.SUPPORTED_MARKETS) == set(mdb._PATTERNS) == set(mdb._YF_SUFFIX) == set(mdb._ISIN_PREFIX)


# --------------------------------------------------------------- excel_parser
@pytest.mark.parametrize("header, role", [
    ("Symbol", "ticker"), ("  NSE Code ", "ticker"), ("Stock.", "ticker"),
    ("Company Name", "name"), ("ISIN", "isin"), ("Purchase Date", "date"),
    ("Qty", "qty"), ("Avg Price", "price"), ("Remarks", None), ("", None),
])
def test_col_role_is_case_space_and_trailing_dot_insensitive(header, role):
    assert xp._col_role(header) == role


@pytest.mark.parametrize("raw, expected", [
    ("1,234.50", 1234.5), ("₹ 99", 99.0), ("$1,000", 1000.0), ("€5", 5.0), ("£7.5", 7.5),
    (12, 12.0), ("abc", None), ("", None), (None, None),
])
def test_parse_float_strips_currency_symbols_and_commas(raw, expected):
    assert xp._parse_float(raw) == expected


def test_parse_date_cell_handles_datetime_date_text_and_junk():
    assert xp._parse_date_cell(dt.datetime(2024, 3, 5, 10, 0)) == "2024-03-05"
    assert xp._parse_date_cell(dt.date(2024, 3, 5)) == "2024-03-05"
    assert xp._parse_date_cell("05-03-2024") == "2024-03-05"          # day-first wins
    assert xp._parse_date_cell("2024-03-05") == "2024-03-05"
    assert xp._parse_date_cell("") is None and xp._parse_date_cell(None) is None
    assert xp._parse_date_cell("None") is None and xp._parse_date_cell("nan") is None
    assert xp._parse_date_cell("not a date at all") is None


def _book(sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_find_header_row_skips_preamble_and_maps_first_column_per_role():
    wb = openpyxl.load_workbook(io.BytesIO(_book({"S": [
        ["My portfolio"], [None, None], ["Symbol", "Name", "Symbol", "Qty"], ["TCS", "x", "y", 1]]})))
    row, roles = xp._find_header_row(wb["S"])
    assert row == 3 and roles == {"ticker": 1, "name": 2, "qty": 4}


def test_find_header_row_none_when_nothing_recognisable():
    wb = openpyxl.load_workbook(io.BytesIO(_book({"S": [["foo", "bar"], [1, 2]]})))
    assert xp._find_header_row(wb["S"]) is None


def test_resolve_by_symbol_with_holding_fields(nse):
    rec = xp._resolve("tcs-EQ", "", "", "india", "Sheet1", raw_date="05-03-2024", raw_qty="1,0", raw_price="₹3,500.5")
    assert rec["yf_ticker"] == "TCS.NS" and rec["symbol"] == "TCS.NS" and rec["matched_via"] == "symbol"
    assert rec["sheet"] == "Sheet1" and rec["name"] == "Tata Consultancy Services Limited"
    assert rec["purchase_date"] == "2024-03-05" and rec["quantity"] == 10.0 and rec["purchase_price"] == 3500.5


def test_resolve_holding_fields_are_omitted_when_blank_or_unparseable(nse):
    rec = xp._resolve("TCS", "", "", "india", "S", raw_date="garbage", raw_qty="n/a", raw_price="")
    assert "purchase_date" not in rec and "quantity" not in rec and "purchase_price" not in rec


def test_resolve_quantity_zero_is_kept():
    # a zero is a real parsed number, not "missing"
    assert xp._parse_float("0") == 0.0


def test_resolve_falls_back_to_isin_for_india_only(nse):
    rec = xp._resolve("UNKNOWN", "", "INE009A01021", "india", "S")
    assert rec["yf_ticker"] == "INFY.NS" and rec["matched_via"] == "ISIN" and rec["isin"] == "INE009A01021"
    assert xp._resolve("UNKNOWN", "", "US0378331005", "us", "S") is None
    assert xp._resolve("", "", "INE009A", "india", "S") is None           # too short to be an ISIN


def test_resolve_falls_back_to_fuzzy_name_and_reports_no_match(mkt):
    rec = xp._resolve("", "Toyota Motors", "", "japan", "S")
    assert rec["yf_ticker"] == "7203.T" and rec["matched_via"] == "name (fuzzy)"
    assert xp._resolve("", "Zebra Quartz Mining", "", "japan", "S") is None
    assert xp._resolve("", "", "", "india", "S") is None


def test_parse_excel_reads_holdings_dedups_and_reports_unmatched(nse):
    data = _book({"Holdings": [
        ["Symbol", "Company", "Qty", "Buy Price", "Date"],
        ["TCS", "", 10, 3500, dt.datetime(2024, 3, 5)],
        ["TCS", "", 99, 1, "01-01-2020"],                  # duplicate ticker -> first row kept
        ["INFY", "", "5", "1,500.00", None],
        ["ZZZ", "Mystery Corp", 1, 1, None],
        ["ZZ2", "Other Mystery", 1, 1, None],
        [None, None, None, None, None],                    # empty row skipped
        ["-", "None", 1, 1, None],                         # placeholder ticker + name 'None'
    ]})
    out = xp.parse_excel(data, "india")
    stocks = {s["yf_ticker"]: s for s in out["stocks"]}
    assert set(stocks) == {"TCS.NS", "INFY.NS"}
    assert stocks["TCS.NS"]["quantity"] == 10.0 and stocks["TCS.NS"]["purchase_date"] == "2024-03-05"
    assert stocks["INFY.NS"]["purchase_price"] == 1500.0 and "purchase_date" not in stocks["INFY.NS"]
    assert out["sheets_scanned"] == ["Holdings"]
    assert out["warnings"] == ["Sheet 'Holdings': 2 rows could not be matched (e.g. Mystery Corp, Other Mystery)"]


def test_parse_excel_warning_lists_at_most_five_examples(nse):
    rows = [["Symbol", "Company"]] + [[f"X{i}", f"Unknown Co {i}"] for i in range(8)]
    out = xp.parse_excel(_book({"S": rows}), "india")
    assert "8 rows could not be matched" in out["warnings"][0]
    assert out["warnings"][0].count("Unknown Co") == 5


def test_parse_excel_without_header_scans_text_of_the_sheet(nse):
    data = _book({"Notes": [["bought INE467B01029 yesterday"], ["and INFY too"]], "Empty": [["nothing here"]]})
    out = xp.parse_excel(data, "india")
    assert sorted(s["yf_ticker"] for s in out["stocks"]) == ["INFY.NS", "TCS.NS"]
    assert out["sheets_scanned"] == ["Notes"]
    assert all(s["sheet"] == "Notes" and s["symbol"] == s["yf_ticker"] for s in out["stocks"])


def test_parse_excel_same_ticker_on_two_sheets_is_kept_once(nse):
    data = _book({"A": [["Symbol"], ["TCS"]], "B": [["Symbol"], ["TCS"], ["INFY"]]})
    out = xp.parse_excel(data, "india")
    sheets = {s["yf_ticker"]: s["sheet"] for s in out["stocks"]}
    assert sheets == {"TCS.NS": "A", "INFY.NS": "B"}
    assert out["sheets_scanned"] == ["A", "B"]


def test_parse_excel_other_market(nse, mkt):
    data = _book({"S": [["Ticker", "Shares"], ["7203", 3]]})
    out = xp.parse_excel(data, "japan")
    assert [(s["yf_ticker"], s["quantity"]) for s in out["stocks"]] == [("7203.T", 3.0)]


# ------------------------------------------------------------- source bug
@pytest.mark.xfail(
    strict=True, raises=TypeError,
    reason="market_db.py:_db('india') keys by_yf by the bare NSE symbol but maps by_code/by_name to "
           "'<SYM>.NS', so lookup('TCS.NS') and every India lookup_by_name()/fuzzy-name fallback "
           "(used by excel_parser._resolve) returns None.")
def test_india_name_and_suffixed_lookups_resolve(nse):
    assert mdb.lookup("TCS.NS", "india")["yf_ticker"] == "TCS.NS"
    assert mdb.lookup_by_name("Infosys Limited", "india")["yf_ticker"] == "INFY.NS"
