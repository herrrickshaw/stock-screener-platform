"""Offline tests for backend.damodaran (sector benchmark loader) using a fake xlrd workbook."""
import math
import os

import pytest

import damodaran as dm


class FakeSheet:
    def __init__(self, rows):
        self.rows = rows
        self.nrows = len(rows)
        self.ncols = max((len(r) for r in rows), default=0)

    def cell_value(self, r, c):
        return self.rows[r][c]


class FakeBook:
    def __init__(self, rows, sheet_name="Industry Averages"):
        self.rows, self.sheet_name = rows, sheet_name

    def sheet_by_name(self, name):
        assert name == self.sheet_name
        return FakeSheet(self.rows)


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    monkeypatch.setattr(dm, "_CACHE", {})


# -------------------------------------------------------------- _safe_float
@pytest.mark.parametrize("v, expected", [
    (1, 1.0), ("2.5", 2.5), (0, 0.0), ("", None), (None, None), ("abc", None),
    (float("nan"), None), (float("inf"), None), (-float("inf"), None), ([1], None),
])
def test_safe_float(v, expected):
    assert dm._safe_float(v) == expected


def test_safe_float_keeps_zero_distinct_from_missing():
    assert dm._safe_float(0) == 0.0 and dm._safe_float(0) is not None


# -------------------------------------------------------------- _load_sheet
def _sheet_rows():
    return [
        ["Damodaran", "", ""],
        ["Date updated", "Jan", ""],
        ["Industry Name", "Number of firms", "Trailing PE"],
        ["Software", 10, 25.0],
        ["  Steel  ", 5, 8.0],
        ["", 3, 99.0],            # blank name -> skipped
        [123, 3, 99.0],           # non-string name -> skipped
        ["Total Market", 15, 17.0],
    ]


def test_load_sheet_finds_header_row_and_returns_stripped_names(monkeypatch):
    monkeypatch.setattr(dm.xlrd, "open_workbook", lambda path: FakeBook(_sheet_rows()))
    rows = dm._load_sheet("whatever.xls")
    assert [r["Industry Name"] for r in rows] == ["Software", "Steel", "Total Market"]
    assert rows[0] == {"Industry Name": "Software", "Number of firms": 10, "Trailing PE": 25.0}


def test_load_sheet_without_header_row_returns_empty(monkeypatch):
    monkeypatch.setattr(dm.xlrd, "open_workbook", lambda path: FakeBook([["a", "b"], ["c", "d"]]))
    assert dm._load_sheet("x.xls") == []


def test_load_sheet_header_match_is_exact_after_strip(monkeypatch):
    rows = [["  Industry Name  ", "X"], ["Alpha", 1]]
    monkeypatch.setattr(dm.xlrd, "open_workbook", lambda path: FakeBook(rows))
    assert [r["Industry Name"] for r in dm._load_sheet("x")] == ["Alpha"]


def test_load_sheet_real_damodaran_file_smoke():
    rows = dm._load_sheet(os.path.join(dm.DATA_DIR, "peIndia.xls"))
    assert len(rows) > 50
    assert all(isinstance(r["Industry Name"], str) and r["Industry Name"] for r in rows)
    assert "Trailing PE" in rows[0]


# --------------------------------------------------------- _build_benchmarks
def _fake_loader(table, calls=None):
    def loader(path):
        base = os.path.basename(path)
        if calls is not None:
            calls.append(base)
        if base not in table:
            raise FileNotFoundError(path)
        return table[base]
    return loader


INDIA_TABLE = {
    "peIndia.xls": [{"Industry Name": "Software", "Number of firms": 10, "Trailing PE": 25.0,
                     "Current PE": 26.0, "Forward PE": 22.0, "PEG Ratio": 1.2,
                     "Expected growth - next 5 years": 0.15}],
    "marginIndia.xls": [{"Industry Name": "Software", "Gross Margin": 0.5, "Net Margin": 0.2,
                         "Pre-tax Unadjusted Operating Margin": 0.3}],
    "roeIndia.xls": [{"Industry Name": "Software", "ROE (unadjusted)": 0.25}],
    "dbtfundIndia.xls": [{"Industry Name": "Software", "Market D/E (unadjusted)": 0.1}],
    "histgrIndia.xls": [{"Industry Name": "Software", "CAGR in Revenues- Last 5 years": 0.12,
                         "CAGR in Net Income- Last 5 years": 0.14}],
}


def test_build_benchmarks_india_merges_all_five_files(monkeypatch):
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader(INDIA_TABLE))
    b = dm._build_benchmarks("india")["Software"]
    assert b == {"industry": "Software", "num_firms": 10.0, "trailing_pe": 25.0, "current_pe": 26.0,
                 "forward_pe": 22.0, "peg": 1.2, "exp_growth_5y": 0.15, "gross_margin": 0.5,
                 "net_margin": 0.2, "opm": 0.3, "roe": 0.25, "market_de": 0.1,
                 "rev_cagr_5y": 0.12, "ni_cagr_5y": 0.14}


def test_build_benchmarks_file_names_per_region(monkeypatch):
    for region, expected in [("india", ["peIndia.xls", "marginIndia.xls", "roeIndia.xls",
                                        "dbtfundIndia.xls", "histgrIndia.xls"]),
                             ("us", ["pedata.xls", "margin.xls", "roe.xls"]),
                             ("europe", ["peEurope.xls", "marginEurope.xls", "roeEurope.xls"])]:
        calls = []
        table = {k: [] for k in expected}
        monkeypatch.setattr(dm, "_load_sheet", _fake_loader(table, calls))
        assert dm._build_benchmarks(region) == {}
        assert calls == expected


def test_build_benchmarks_missing_india_extras_are_tolerated(monkeypatch):
    table = {k: v for k, v in INDIA_TABLE.items() if k not in ("dbtfundIndia.xls", "histgrIndia.xls")}
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader(table))
    b = dm._build_benchmarks("india")["Software"]
    assert "market_de" not in b and b["roe"] == 0.25


def test_build_benchmarks_missing_core_file_propagates(monkeypatch):
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader({"peIndia.xls": []}))
    with pytest.raises(FileNotFoundError):
        dm._build_benchmarks("india")


def test_build_benchmarks_operating_margin_label_precedence_and_none_skipping(monkeypatch):
    rows = lambda **kw: [{"Industry Name": "X", **kw}]
    table = {"pedata.xls": [], "roe.xls": []}
    full = rows(**{"Pre-tax, Pre-stock compensation Operating Margin": 0.4,
                   "Pre-tax Unadjusted Operating Margin": 0.3, "Operating Margin": 0.2})
    table["margin.xls"] = full
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader(table))
    assert dm._build_benchmarks("us")["X"]["opm"] == 0.4
    table["margin.xls"] = rows(**{"Pre-tax, Pre-stock compensation Operating Margin": "",
                                  "Pre-tax Unadjusted Operating Margin": 0.3})
    assert dm._build_benchmarks("us")["X"]["opm"] == 0.3
    table["margin.xls"] = rows(**{"Operating Margin": 0.0})        # zero is a real value, kept
    assert dm._build_benchmarks("us")["X"]["opm"] == 0.0
    table["margin.xls"] = rows(**{"Gross Margin": 0.5})
    assert "opm" not in dm._build_benchmarks("us")["X"]


def test_build_benchmarks_blank_cells_become_none(monkeypatch):
    table = dict(INDIA_TABLE)
    table["peIndia.xls"] = [{"Industry Name": "Software", "Trailing PE": "", "Current PE": float("nan")}]
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader(table))
    b = dm._build_benchmarks("india")["Software"]
    assert b["trailing_pe"] is None and b["current_pe"] is None and b["peg"] is None


def test_build_benchmarks_unknown_region_uses_india_suffix(monkeypatch):
    calls = []
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader({"peIndia.xls": [], "marginIndia.xls": [],
                                                        "roeIndia.xls": []}, calls))
    dm._build_benchmarks("mars")
    assert calls[:3] == ["peIndia.xls", "marginIndia.xls", "roeIndia.xls"]


# ------------------------------------------------------------ cache + lookups
@pytest.fixture
def india(monkeypatch):
    table = dict(INDIA_TABLE)
    table["peIndia.xls"] = INDIA_TABLE["peIndia.xls"] + [
        {"Industry Name": "Steel", "Trailing PE": 8.0},
        {"Industry Name": "Auto Parts", "Trailing PE": 14.0},
        {"Industry Name": "Banks (Regional)", "Trailing PE": 11.0},
        {"Industry Name": "Software (System & Application)", "Trailing PE": 30.0},
    ]
    table["roeIndia.xls"] = INDIA_TABLE["roeIndia.xls"] + [
        {"Industry Name": "Software (System & Application)", "ROE (unadjusted)": 0.3}]
    calls = []
    monkeypatch.setattr(dm, "_load_sheet", _fake_loader(table, calls))
    return calls


def test_cache_builds_each_region_once(india):
    dm._get_cache("india")
    dm._get_cache("india")
    assert india.count("peIndia.xls") == 1


def test_lookup_industry_direct_map_is_case_and_space_insensitive(india):
    assert dm.lookup_industry("  IT ") == "Software (System & Application)"
    assert dm.lookup_industry("Banking") == "Banks (Regional)"
    assert india == []                                  # direct hit never loads the files


def test_lookup_industry_empty_input_is_none(india):
    assert dm.lookup_industry("") is None and dm.lookup_industry(None) is None


def test_lookup_industry_fuzzy_matches_against_loaded_names(india):
    assert dm.lookup_industry("Steell") == "Steel"           # not in the direct map -> fuzzy
    assert dm.lookup_industry("qqqqqqqq") is None


def test_lookup_industry_fuzzy_cutoff_is_half(india):
    assert dm.lookup_industry("Auto Part") == "Auto Parts"


def test_get_sector_benchmarks_and_value_helpers(india):
    b = dm.get_sector_benchmarks("IT")
    assert b["industry"] == "Software (System & Application)"
    assert dm.get_sector_pe("IT") == 30.0
    assert dm.get_sector_roe("IT") == 0.3
    assert dm.get_sector_benchmarks("zzzzzzzz") is None
    assert dm.get_sector_pe("zzzzzzzz") is None and dm.get_sector_roe("zzzzzzzz") is None


def test_get_sector_benchmarks_direct_map_name_missing_from_data_is_none(india):
    # 'pharma' maps to a Damodaran name that the fake data does not contain
    assert dm.get_sector_benchmarks("pharma") is None


def test_get_all_benchmarks_sorted_by_industry(india):
    names = [b["industry"] for b in dm.get_all_benchmarks()]
    assert names == sorted(names) and "Steel" in names


def test_real_data_known_sector_has_positive_pe():
    pe = dm.get_sector_pe("IT")
    assert pe is not None and pe > 0 and not math.isnan(pe)


def test_lookup_industry_accepts_a_moderately_similar_name(india):
    # similarity to 'Auto Parts' is ~0.76: above the 0.5 cutoff, so it is matched
    assert dm.lookup_industry("Autoparts X") == "Auto Parts"
