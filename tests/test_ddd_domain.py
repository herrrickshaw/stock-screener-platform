"""Offline tests for the DDD domain layer: value objects, domain events, entities, specifications."""
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from domain.market_data.entities import MarketIndex, PriceBar, Sector, Stock
from domain.screening import specifications as sp
from domain.shared import events as ev
from domain.shared.value_objects import (
    DateRange, Exchange, MarketRegime, PEZone, Percentage, Price, ReturnHorizon, Ticker, VIXLevel,
)


# ------------------------------------------------------------- value objects
def test_ticker_normalises_symbol_and_rejects_blank():
    t = Ticker("  reliance ")
    assert t.symbol == "RELIANCE" and t.exchange is Exchange.NSE
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            Ticker(bad)


@pytest.mark.parametrize("exchange, yf", [(Exchange.NSE, "TCS.NS"), (Exchange.BSE, "TCS.BO"),
                                          (Exchange.NASDAQ, "TCS"), (Exchange.NYSE, "TCS"),
                                          (Exchange.UNKNOWN, "TCS")])
def test_ticker_yfinance_symbol_by_exchange(exchange, yf):
    t = Ticker("tcs", exchange)
    assert t.yfinance_symbol == yf and str(t) == yf
    assert t.display == f"TCS [{exchange.value}]"


def test_ticker_is_hashable_value_object():
    assert Ticker("a") == Ticker("A") and len({Ticker("a"), Ticker("A")}) == 1
    assert Ticker("A", Exchange.BSE) != Ticker("A")
    with pytest.raises(Exception):
        Ticker("A").symbol = "B"


def test_price_validation_and_arithmetic():
    assert Price(0).amount == 0
    with pytest.raises(ValueError):
        Price(-0.01)
    assert Price(5, "USD") + Price(2.5, "USD") == Price(7.5, "USD")
    assert Price(5) - Price(2) == Price(3)
    with pytest.raises(ValueError, match="Cannot add"):
        Price(1, "INR") + Price(1, "USD")
    with pytest.raises(ValueError, match="Cannot subtract"):
        Price(1, "INR") - Price(1, "USD")
    with pytest.raises(ValueError):
        Price(1) - Price(2)                          # result would be negative


def test_price_display():
    assert str(Price(1234.5)) == "₹1,234.50" and str(Price(1234.5, "USD")) == "$1,234.50"
    assert Price(1, "EUR").symbol == "$"             # any non-INR currency prints as dollars


def test_percentage_conversions_and_sign():
    assert str(Percentage(5.256)) == "+5.26%" and str(Percentage(-1.0)) == "-1.00%"
    assert str(Percentage(0)) == "+0.00%"
    assert Percentage(25).as_decimal() == 0.25
    assert Percentage.from_decimal(0.1234).value == pytest.approx(12.34)


def test_date_range():
    r = DateRange(date(2026, 1, 1), date(2026, 1, 31))
    assert r.days == 30 and str(r) == "2026-01-01 – 2026-01-31"
    assert r.contains(date(2026, 1, 1)) and r.contains(date(2026, 1, 31))
    assert not r.contains(date(2025, 12, 31)) and not r.contains(date(2026, 2, 1))
    assert DateRange(date(2026, 1, 1), date(2026, 1, 1)).days == 0
    with pytest.raises(ValueError):
        DateRange(date(2026, 1, 2), date(2026, 1, 1))


def test_return_horizons_are_consistent():
    allh = ReturnHorizon.all_horizons()
    assert [h.trading_days for h in allh] == [1, 3, 5, 10, 21, 63, 126, 252]
    assert allh == [ReturnHorizon.next_day(), ReturnHorizon.three_days(), ReturnHorizon.one_week(),
                    ReturnHorizon.two_weeks(), ReturnHorizon.one_month(), ReturnHorizon.three_months(),
                    ReturnHorizon.six_months(), ReturnHorizon.one_year()]
    assert str(ReturnHorizon.one_month()) == "T+21d"
    assert all(h.label == f"T+{h.trading_days}d" for h in allh)


@pytest.mark.parametrize("v, regime, factor", [
    (30.01, "PANIC", 0.25), (30.0, "HIGH_FEAR", 0.5), (22.01, "HIGH_FEAR", 0.5),
    (22.0, "ELEVATED", 0.75), (17.01, "ELEVATED", 0.75), (17.0, "NORMAL", 1.0),
    (12.01, "NORMAL", 1.0), (12.0, "COMPLACENCY", 1.0), (5.0, "COMPLACENCY", 1.0),
])
def test_vix_regime_and_position_factor_boundaries(v, regime, factor):
    vix = VIXLevel(v)
    assert vix.regime == regime and vix.position_size_factor == factor
    assert str(vix) == f"VIX {v:.2f} [{regime}]"


def test_enum_values():
    assert PEZone.NA.value == "N/A" and MarketRegime.BULL_VOLATILE.value == "BULL_VOLATILE"


# -------------------------------------------------------------- domain events
def test_domain_event_defaults_and_names():
    a, b = ev.DomainEvent(), ev.DomainEvent()
    assert a.event_id != b.event_id and isinstance(a.occurred_at, datetime)
    e = ev.BreakoutDetected(ticker="TCS", price=10.0)
    assert e.event_name == "BreakoutDetected" and e.screener == "DarvasBox"
    m = ev.MultiScreenHitDetected()
    assert m.screeners == [] and m.screeners is not ev.MultiScreenHitDetected().screeners


def test_event_bus_dispatches_by_exact_type_only():
    bus = ev.DomainEventBus()
    got = []
    bus.subscribe(ev.BreakoutDetected, lambda e: got.append(("b", e.ticker)))
    bus.subscribe(ev.ReportGenerated, lambda e: got.append(("r", e.path)))
    bus.publish(ev.BreakoutDetected(ticker="A"))
    bus.publish(ev.DomainEvent())                       # base class: no handlers
    bus.publish_all([ev.ReportGenerated(path="/x"), ev.BreakoutDetected(ticker="B")])
    assert got == [("b", "A"), ("r", "/x"), ("b", "B")]


def test_event_bus_handler_errors_are_isolated_and_reported(capsys):
    bus = ev.DomainEventBus()
    got = []

    def bad(e):
        raise RuntimeError("nope")
    bus.subscribe(ev.CacheWarmed, bad)
    bus.subscribe(ev.CacheWarmed, lambda e: got.append(e.symbols_cached))
    bus.publish(ev.CacheWarmed(symbols_cached=3))
    assert got == [3]
    assert "Handler error for CacheWarmed: nope" in capsys.readouterr().out


def test_event_bus_multiple_handlers_run_in_subscription_order():
    bus, got = ev.DomainEventBus(), []
    for i in range(3):
        bus.subscribe(ev.MarketOpenDetected, lambda e, i=i: got.append(i))
    bus.publish(ev.MarketOpenDetected())
    assert got == [0, 1, 2]


def test_singleton_bus_accessor():
    assert ev.get_event_bus() is ev.get_event_bus() and isinstance(ev.get_event_bus(), ev.DomainEventBus)


# ------------------------------------------------------------------- entities
D0 = date(2026, 1, 1)


def bar(i, close=10.0, **kw):
    d = date.fromordinal(D0.toordinal() + i)
    args = dict(open=close, high=close + 1, low=close - 1, close=close, volume=100)
    args.update(kw)
    return PriceBar(d, **args)


def test_price_bar_validation_and_candle_maths():
    with pytest.raises(ValueError, match="High"):
        PriceBar(D0, 10, 9, 10, 10, 1)
    with pytest.raises(ValueError, match="negative"):
        PriceBar(D0, 10, 12, 1, -1, 1)
    with pytest.raises(ValueError, match="negative"):
        PriceBar(D0, -1, 12, 1, 5, 1)
    b = PriceBar(D0, 10, 14, 8, 13, 5)
    assert b.range == 6 and b.is_bullish and b.body_pct == pytest.approx(50.0)
    assert not PriceBar(D0, 10, 10, 10, 10, 1).is_bullish
    assert PriceBar(D0, 10, 10, 10, 10, 1).body_pct == 0          # zero range, no division error


@pytest.mark.parametrize("pe, zone", [
    (None, PEZone.NA), (0, PEZone.NA), (-5, PEZone.NA),
    (15, PEZone.BUY_ZONE), (15.01, PEZone.FAIR_VALUE), (25, PEZone.FAIR_VALUE),
    (25.01, PEZone.CAUTION), (35, PEZone.CAUTION), (35.01, PEZone.SELL_ZONE),
])
def test_sector_pe_classification_boundaries(pe, zone):
    assert Sector.default().classify_pe(pe) is zone


@pytest.mark.parametrize("text, name", [
    ("Financial Services", "Banking/NBFC"), ("Bank", "Banking/NBFC"), ("NBFC", "Banking/NBFC"),
    ("Technology", "IT/Software"), ("Software - Infra", "IT/Software"), ("IT services", "IT/Software"),
    ("Consumer Staples", "FMCG/Consumer"), ("Healthcare", "Pharma/Healthcare"),
    ("Pharmaceuticals", "Pharma/Healthcare"), ("Energy", "Energy/Oil & Gas"), ("Oil", "Energy/Oil & Gas"),
    ("Automobile", "Auto"), ("Vehicles", "Auto"), ("Utilities", "General"), (None, "General"), ("", "General"),
])
def test_sector_from_yfinance_string(text, name):
    assert Sector.from_yfinance_sector(text).name == name


def test_sector_consumer_discretionary_has_its_own_thresholds():
    s = Sector.from_yfinance_sector("Consumer Discretionary")
    assert (s.pe_buy, s.pe_fair, s.pe_caution) == (18, 28, 40)
    assert Sector.from_yfinance_sector("Consumer Cyclical").name == "General"


def test_sector_factories_have_ascending_thresholds():
    for s in (Sector.banking(), Sector.technology(), Sector.fmcg(), Sector.pharma(), Sector.energy(),
              Sector.auto(), Sector.default()):
        assert s.pe_buy < s.pe_fair < s.pe_caution


def test_stock_defaults_company_name_and_price_series_rules():
    s = Stock(Ticker("tcs"))
    assert s.company_name == "TCS" and s.bar_count == 0 and s.current_price is None
    assert Stock(Ticker("tcs"), "Tata").company_name == "Tata"
    s.add_price_bar(bar(0))
    s.add_price_bar(bar(1, close=12))
    for dup in (bar(1), bar(0)):
        with pytest.raises(ValueError, match="not after"):
            s.add_price_bar(dup)
    assert s.bar_count == 2 and s.current_price == Price(12.0, "INR")
    snapshot = s.price_series
    snapshot.clear()
    assert s.bar_count == 2                                         # accessor returns a copy


def test_stock_current_price_currency_follows_exchange():
    us = Stock(Ticker("aapl", Exchange.NASDAQ))
    us.add_price_bar(bar(0, close=5))
    assert us.current_price == Price(5.0, "USD")
    bse = Stock(Ticker("x", Exchange.BSE))
    bse.add_price_bar(bar(0, close=5))
    assert bse.current_price.currency == "INR"


def test_stock_load_price_series_sorts_and_array_columns():
    s = Stock(Ticker("a"))
    s.load_price_series([bar(2, 30), bar(0, 10), bar(1, 20)])
    assert s.get_price_array() == [10, 20, 30]
    assert s.get_price_array("HIGH") == [11, 21, 31] and s.get_price_array("volume") == [100] * 3


def test_stock_load_from_dataframe_accepts_both_casings_and_skips_bad_rows():
    idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    df = pd.DataFrame({"Open": [1.0, 2.0, 3.0], "High": [2.0, 1.0, 4.0], "Low": [0.5, 3.0, 2.0],
                       "Close": [1.5, 2.0, 3.5], "Volume": [10, 20, 30]}, index=idx)
    s = Stock(Ticker("a"))
    s.load_from_dataframe(df)                               # row 2 has High < Low -> skipped
    assert [b.close for b in s.price_series] == [1.5, 3.5]
    lower = df.rename(columns=str.lower)
    s2 = Stock(Ticker("a"))
    s2.load_from_dataframe(lower)
    assert s2.bar_count == 2 and s2.price_series[0].date == date(2026, 1, 1)


def test_stock_load_from_dataframe_accepts_plain_date_index():
    df = pd.DataFrame({"close": [5.0], "open": [5.0], "high": [6.0], "low": [4.0], "volume": [1]},
                      index=[date(2026, 2, 2)])
    s = Stock(Ticker("a"))
    s.load_from_dataframe(df)
    assert s.price_series[0].date == date(2026, 2, 2)


def test_stock_days_since_listing():
    s = Stock(Ticker("a"), listing_date=D0)
    assert s.days_since_listing == 0                                # no bars -> bar_count
    s.load_price_series([bar(0), bar(10)])
    assert s.days_since_listing == 10
    assert Stock(Ticker("a")).days_since_listing == 0
    t = Stock(Ticker("a"))
    t.load_price_series([bar(0), bar(1)])
    assert t.days_since_listing == 2                                # no listing date -> bar count


def test_stock_eligibility_thresholds():
    s = Stock(Ticker("a"))
    s.load_price_series([bar(i) for i in range(204)])
    assert s.is_darvas_eligible() and s.is_darvas_eligible(204) and not s.is_darvas_eligible(205)
    assert not s.is_golden_cross_eligible()
    s.load_price_series([bar(i) for i in range(205)])
    assert s.is_golden_cross_eligible()
    t = Stock(Ticker("a"))
    t.load_price_series([bar(i) for i in range(34)])
    assert not t.is_darvas_eligible()
    t.load_price_series([bar(i) for i in range(35)])
    assert t.is_darvas_eligible()


def test_stock_pe_zone_uses_sector_trailing_then_forward():
    s = Stock(Ticker("a"), trailing_pe=None, forward_pe=10.0)
    assert s.pe_zone is PEZone.BUY_ZONE                              # default sector, forward fallback
    s.trailing_pe = 40.0
    assert s.pe_zone is PEZone.SELL_ZONE
    s.sector = Sector.fmcg()
    assert s.pe_zone is PEZone.BUY_ZONE
    assert Stock(Ticker("a")).pe_zone is PEZone.NA


def test_stock_event_outbox_drains_once():
    s = Stock(Ticker("a"))
    s.record_event("e1")
    s.record_event("e2")
    assert s.pull_events() == ["e1", "e2"] and s.pull_events() == []


def test_stock_repr_mentions_ticker_bars_and_price():
    s = Stock(Ticker("tcs"))
    s.add_price_bar(bar(0, close=7))
    assert repr(s) == f"Stock(TCS [NSE], bars=1, price={Price(7.0)})"


def _index(closes):
    idx = MarketIndex("^X", "X", "IN")
    idx._price_series = [bar(i, c) for i, c in enumerate(closes)]
    return idx


def test_market_index_levels_and_moving_averages():
    idx = _index([float(i) for i in range(1, 201)])
    assert idx.bar_count == 200 and idx.current_level == 200.0
    assert idx.dma200 == pytest.approx(100.5) and idx.dma50 == pytest.approx(sum(range(151, 201)) / 50)
    short = _index([1.0] * 199)
    assert short.dma200 is None and short.dma50 == 1.0
    assert _index([1.0] * 49).dma50 is None
    assert _index([]).current_level is None


def test_market_index_load_from_dataframe_sorts_and_skips_invalid():
    df = pd.DataFrame({"Open": [2.0, 1.0, 3.0], "High": [3.0, 2.0, 1.0], "Low": [1.0, 0.5, 2.0],
                       "Close": [2.5, 1.5, 2.5], "Volume": [1, 2, 3]},
                      index=pd.to_datetime(["2026-01-02", "2026-01-01", "2026-01-03"]))
    idx = MarketIndex("^X", "X", "IN")
    idx.load_from_dataframe(df)                            # third row High < Low -> skipped
    assert [b.close for b in idx._price_series] == [1.5, 2.5]


def test_regime_needs_enough_history():
    assert _index([1.0] * 204).classify_regime() is MarketRegime.SIDEWAYS
    rising = _index([float(i) for i in range(1, 206)])
    assert rising.classify_regime() is MarketRegime.BULL


def test_regime_bull_bear_sideways():
    flat = [100.0] * 200
    bull = _index(flat + [101, 102, 103, 104, 130])           # far above DMA, rising
    assert bull.classify_regime() is MarketRegime.BULL
    bear = _index(flat + [99, 98, 97, 96, 70])
    assert bear.classify_regime() is MarketRegime.BEAR
    near = _index(flat + [100, 100, 100, 100, 101])           # within 1.5 % of the DMA
    assert near.classify_regime() is MarketRegime.SIDEWAYS
    # above DMA but falling over the slope window -> neither bull nor bear
    mixed = _index(flat + [160, 160, 150, 145, 142, 140])
    assert mixed.classify_regime() is MarketRegime.SIDEWAYS


def test_regime_sideways_band_is_inclusive_and_parameterised():
    base = [100.0] * 200 + [100.0, 100.0, 100.0, 100.0]
    # last close 102 -> dma ~100.01, pct ~ +2 %
    idx = _index(base + [102.0])
    assert idx.classify_regime() is MarketRegime.BULL
    assert idx.classify_regime(sideways_pct=5.0) is MarketRegime.SIDEWAYS
    assert idx.classify_regime(dma_period=10, slope_bars=2, sideways_pct=0.1) is MarketRegime.BULL


# --------------------------------------------------------------- specifications
class Const(sp.Specification):
    def __init__(self, v):
        self.v = v
        self.calls = 0

    def is_satisfied_by(self, candidate):
        self.calls += 1
        return self.v

    def explain(self):
        return f"const {self.v}"


def test_boolean_composition_truth_tables_and_explanations():
    T, F = Const(True), Const(False)
    assert T.and_(T).is_satisfied_by(0) and not T.and_(F).is_satisfied_by(0) and not F.and_(T).is_satisfied_by(0)
    assert T.or_(F).is_satisfied_by(0) and F.or_(T).is_satisfied_by(0) and not F.or_(F).is_satisfied_by(0)
    assert F.not_().is_satisfied_by(0) and not T.not_().is_satisfied_by(0)
    assert T.and_(F).explain() == "(const True) AND (const False)"
    assert T.or_(F).explain() == "(const True) OR (const False)"
    assert T.not_().explain() == "NOT (const True)"


def test_composition_short_circuits():
    a, b = Const(False), Const(True)
    a.and_(b).is_satisfied_by(0)
    assert b.calls == 0
    c, d = Const(True), Const(False)
    c.or_(d).is_satisfied_by(0)
    assert d.calls == 0


def cand(**kw):
    return sp.ScreeningCandidate(symbol="X", suffix=".NS", **kw)


def test_candidate_market_cap_and_financial_flag():
    assert cand(market_cap=5e9).market_cap_cr == 500.0 and cand().market_cap_cr == 0.0
    assert cand(sector="Private Bank").is_financial_company
    assert cand(sector="Capital Goods").is_financial_company       # 'capital' substring is treated as financial
    assert not cand(sector="Software").is_financial_company and not cand(sector="").is_financial_company


def test_candidate_row_and_series_helpers():
    df = pd.DataFrame({"2025": [10.0, np.nan], "2024": [20.0, 5.0], "2023": [30.0, 6.0]},
                      index=["Net Income", "Gross Profit"])
    c = cand()
    assert c._row(df, "Net Income") == 10.0 and c._row(df, "Net Income", col=2) == 30.0
    assert c._row(df, "Missing", "Net Income") == 10.0                 # first known alias wins
    assert c._row(df, "Gross Profit", col=0) is None                   # NaN -> None
    assert c._row(df, "Net Income", col=9) is None                     # out of range -> None
    assert c._row(None, "Net Income") is None and c._row(df.iloc[0:0], "Net Income") is None
    assert c._series(df, "Gross Profit") == [5.0, 6.0]
    assert c._series(df, "Nope", "Net Income") == [10.0, 20.0, 30.0]
    assert c._series(None, "Net Income") == [] and c._series(df, "Nope") == []


def ohlc(closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({"High": highs if highs is not None else [c + 1 for c in closes],
                         "Low": lows if lows is not None else [c - 1 for c in closes],
                         "Close": closes}, index=pd.RangeIndex(n))


def test_darvas_spec_requires_data_and_min_history():
    spec = sp.DarvasBoxSpec()
    assert not spec.is_satisfied_by(cand())
    df = ohlc([10.0] * 22)
    assert not spec.is_satisfied_by(cand(ohlc_df=df, bar_count=22))       # < confirm + 20 = 23
    assert not spec.is_satisfied_by(cand(ohlc_df=df, bar_count=23))       # no box top at all


def test_darvas_spec_detects_breakout_over_confirmed_box_top():
    closes = [10.0] * 30
    highs = [11.0] * 30
    highs[20] = 15.0                                     # box top, followed by 3 lower highs
    closes[-1] = 16.0                                    # breakout close
    spec = sp.DarvasBoxSpec(confirm=3)
    assert spec.is_satisfied_by(cand(ohlc_df=ohlc(closes, highs), bar_count=30))
    closes[-1] = 15.0                                    # equal to the top is not a breakout
    assert not spec.is_satisfied_by(cand(ohlc_df=ohlc(closes, highs), bar_count=30))


def test_darvas_spec_ignores_box_tops_older_than_60_bars_and_needs_strictly_lower_highs():
    n = 90
    closes, highs = [10.0] * n, [11.0] * n
    highs[10] = 20.0                                     # 79 bars back: outside the lookback
    closes[-1] = 30.0
    assert not sp.DarvasBoxSpec().is_satisfied_by(cand(ohlc_df=ohlc(closes, highs), bar_count=n))
    highs2 = [11.0] * 30
    highs2[20] = 15.0
    highs2[22] = 15.0                                    # confirmation bar equals the top -> not confirmed
    c2 = [10.0] * 30
    c2[-1] = 16.0
    spec = sp.DarvasBoxSpec(confirm=3)
    got = spec.is_satisfied_by(cand(ohlc_df=ohlc(c2, highs2), bar_count=30))
    assert bool(got)                                     # the 15.0 at idx 22 (followed by lower highs) is a top


def test_darvas_spec_explain_mentions_parameters():
    assert "confirm=5 days" in sp.DarvasBoxSpec(confirm=5).explain()
    assert "vol≥2.5×avg" in sp.DarvasBoxSpec(vol_threshold=2.5).explain()


def _cross_series(kind):
    # 250 bars: a long decline then rise so the 50 DMA crosses the 200 DMA exactly on the last bar
    if kind == "above":
        return [100.0] * 150 + [200.0] * 100
    return [100.0] * 250


def test_dma50_above_dma200_spec():
    spec = sp.DMA50AboveDMA200Spec()
    up = pd.DataFrame({"Close": [100.0] * 150 + [200.0] * 100})
    assert spec.is_satisfied_by(cand(ohlc_df=up, bar_count=250))
    flat = pd.DataFrame({"Close": [100.0] * 250})
    assert not spec.is_satisfied_by(cand(ohlc_df=flat, bar_count=250))            # equal -> not above
    assert not spec.is_satisfied_by(cand(ohlc_df=up, bar_count=204))
    assert not spec.is_satisfied_by(cand())
    assert "50 DMA" in spec.explain()


def test_golden_cross_spec_fires_only_on_the_crossing_bar():
    spec = sp.GoldenCrossSpec()
    # 200 bars at 100, then ramp so 50DMA passes 200DMA on the last bar only
    closes = [100.0] * 205
    cross = pd.Series(closes + [100.0] * 0)
    # find a series where cross happens exactly at the end by search
    base = [100.0] * 160 + [90.0] * 45                      # 50DMA < 200DMA at the end
    s = pd.Series(base)
    d50, d200 = s.rolling(50).mean(), s.rolling(200).mean()
    assert d50.iloc[-1] < d200.iloc[-1]
    assert not spec.is_satisfied_by(cand(ohlc_df=pd.DataFrame({"Close": base}), bar_count=205))
    # extend with high closes until the cross, then assert the first crossing bar is the only hit
    hits = []
    series = list(base)
    for k in range(60):
        series.append(500.0)
        df = pd.DataFrame({"Close": series})
        hits.append(spec.is_satisfied_by(cand(ohlc_df=df, bar_count=len(series))))
    assert sum(hits) == 1 and hits.index(True) > 0
    assert not spec.is_satisfied_by(cand(bar_count=300))
    assert not spec.is_satisfied_by(cand(ohlc_df=pd.DataFrame({"Close": base}), bar_count=204))
    assert "Golden Cross" in spec.explain()


def fin(rows, cols=("0", "1", "2", "3")):
    """Statement frame: rows -> list of values, newest column first."""
    return pd.DataFrame({k: v for k, v in rows.items()}, index=list(cols)[:len(next(iter(rows.values())))]).T


def test_piotroski_spec_scores_nine_for_a_perfect_company():
    inc = fin({"Net Income": [20.0, 10.0], "Total Revenue": [200.0, 100.0], "Gross Profit": [100.0, 40.0]})
    bal = fin({"Total Assets": [100.0, 100.0], "Long Term Debt": [10.0, 30.0],
               "Current Assets": [60.0, 40.0], "Current Liabilities": [20.0, 20.0],
               "Share Issued": [10.0, 10.0]})
    cf = fin({"Operating Cash Flow": [30.0]})
    c = cand(income_stmt=inc, balance_sheet=bal, cash_flow=cf)
    assert sp.PiotroskiSpec(min_score=9).is_satisfied_by(c)
    assert sp.PiotroskiSpec().min_score == 7


def test_piotroski_spec_threshold_and_exclusions():
    inc = fin({"Net Income": [20.0, 10.0], "Total Revenue": [200.0, 100.0], "Gross Profit": [100.0, 40.0]})
    bal = fin({"Total Assets": [100.0, 100.0], "Long Term Debt": [10.0, 30.0],
               "Current Assets": [60.0, 40.0], "Current Liabilities": [20.0, 20.0],
               "Share Issued": [10.0, 10.0]})
    cf = fin({"Operating Cash Flow": [30.0]})
    assert not sp.PiotroskiSpec().is_satisfied_by(cand(income_stmt=inc, balance_sheet=bal, cash_flow=cf,
                                                       sector="Banks"))
    assert not sp.PiotroskiSpec().is_satisfied_by(cand())
    assert not sp.PiotroskiSpec().is_satisfied_by(cand(income_stmt=inc.iloc[0:0]))


def test_piotroski_spec_dilution_and_missing_share_data():
    # Only ROA>0 passes among the data-driven tests; share-count test defaults to 1 when absent
    inc = fin({"Net Income": [10.0, 10.0]})
    bal = fin({"Total Assets": [100.0, 100.0]})
    c = cand(income_stmt=inc, balance_sheet=bal, cash_flow=fin({"Operating Cash Flow": [-5.0]}))
    assert sp.PiotroskiSpec(min_score=2).is_satisfied_by(c)          # ROA>0 + no-share-data point
    assert not sp.PiotroskiSpec(min_score=3).is_satisfied_by(c)
    bal2 = fin({"Total Assets": [100.0, 100.0], "Share Issued": [12.0, 10.0]})
    c2 = cand(income_stmt=inc, balance_sheet=bal2, cash_flow=fin({"Operating Cash Flow": [-5.0]}))
    assert not sp.PiotroskiSpec(min_score=2).is_satisfied_by(c2)     # dilution loses the point
    assert "7/9" in sp.PiotroskiSpec().explain()


def coffee_candidate(**over):
    inc = fin({"Total Revenue": [200.0, 150.0, 100.0], "EBIT": [60.0, 45.0, 30.0],
               "Net Income": [40.0, 30.0, 20.0]})
    bal = fin({"Total Assets": [200.0, 180.0, 160.0], "Current Liabilities": [50.0, 50.0, 50.0]})
    args = dict(income_stmt=inc, balance_sheet=bal, market_cap=6e9, debt_to_equity=0.5)
    args.update(over)
    return cand(**args)


def test_coffee_can_spec_happy_path_and_fail_reasons():
    spec = sp.CoffeeCanSpec()
    assert spec.is_satisfied_by(coffee_candidate())
    assert not spec.is_satisfied_by(coffee_candidate(sector="Insurance"))
    assert not spec.is_satisfied_by(cand())
    assert not spec.is_satisfied_by(coffee_candidate(market_cap=4.99e9))            # < 500 Cr
    assert spec.is_satisfied_by(coffee_candidate(market_cap=5.0e9))                 # exactly 500 Cr
    assert not spec.is_satisfied_by(coffee_candidate(debt_to_equity=1.0))
    assert spec.is_satisfied_by(coffee_candidate(debt_to_equity=0.99))
    assert spec.is_satisfied_by(coffee_candidate(debt_to_equity=None))


def test_coffee_can_spec_debt_to_equity_percent_convention():
    # yfinance reports D/E in percent: values above 10 are divided by 100
    spec = sp.CoffeeCanSpec()
    assert spec.is_satisfied_by(coffee_candidate(debt_to_equity=50.0))              # 0.5
    assert not spec.is_satisfied_by(coffee_candidate(debt_to_equity=150.0))         # 1.5


def test_coffee_can_spec_growth_roce_and_loss_year_rules():
    spec = sp.CoffeeCanSpec()
    bal = coffee_candidate().balance_sheet
    slow = fin({"Total Revenue": [105.0, 102.0, 100.0], "EBIT": [60.0, 45.0, 30.0], "Net Income": [4.0, 3.0, 2.0]})
    assert not spec.is_satisfied_by(coffee_candidate(income_stmt=slow))              # CAGR ~2.5 %
    loss = fin({"Total Revenue": [200.0, 150.0, 100.0], "EBIT": [60.0, 45.0, 30.0], "Net Income": [40.0, -1.0, 20.0]})
    assert not spec.is_satisfied_by(coffee_candidate(income_stmt=loss))
    lowroce = fin({"Total Revenue": [200.0, 150.0, 100.0], "EBIT": [5.0, 4.0, 3.0], "Net Income": [4.0, 3.0, 2.0]})
    assert not spec.is_satisfied_by(coffee_candidate(income_stmt=lowroce))
    one_year = fin({"Total Revenue": [200.0], "EBIT": [60.0], "Net Income": [40.0]})
    assert not spec.is_satisfied_by(coffee_candidate(income_stmt=one_year, balance_sheet=bal))
    zero_base = fin({"Total Revenue": [200.0, 150.0, 0.0], "EBIT": [60.0, 45.0, 30.0], "Net Income": [4.0, 3.0, 2.0]})
    assert not spec.is_satisfied_by(coffee_candidate(income_stmt=zero_base))
    assert "Coffee Can" in spec.explain() and "₹500Cr" in spec.explain()


def test_coffee_can_spec_cagr_boundary_is_inclusive():
    # CAGR exactly 10 % over 2 periods: 110 / 100
    inc = fin({"Total Revenue": [121.0, 110.0, 100.0], "EBIT": [60.0, 45.0, 30.0], "Net Income": [4.0, 3.0, 2.0]})
    assert sp.CoffeeCanSpec(min_cagr=10).is_satisfied_by(coffee_candidate(income_stmt=inc))
    assert not sp.CoffeeCanSpec(min_cagr=10.5).is_satisfied_by(coffee_candidate(income_stmt=inc))


def magic_candidate(**over):
    inc = fin({"EBIT": [40.0, 30.0], "Net Income": [25.0, 20.0]})
    bal = fin({"Total Assets": [200.0, 200.0], "Current Liabilities": [50.0, 50.0]})
    args = dict(income_stmt=inc, balance_sheet=bal, market_cap=3e9, total_debt=1e8, total_cash=5e7, book_value=10.0)
    args.update(over)
    return cand(**args)


def test_magic_formula_spec_thresholds():
    # ebit 40 / capital 150 = 26.7 % ; ev = 3e9 + 1e8 - 5e7 -> ey tiny (EBIT in same units as mcap?)
    spec = sp.MagicFormulaSpec(min_roic=15, min_ey=0.0)
    assert spec.is_satisfied_by(magic_candidate())
    assert not sp.MagicFormulaSpec(min_ey=8).is_satisfied_by(magic_candidate())             # EY ~1e-6 %
    big = magic_candidate(income_stmt=fin({"EBIT": [4e8, 3e8], "Net Income": [2.5e8, 2e8]}),
                          balance_sheet=fin({"Total Assets": [2e9, 2e9], "Current Liabilities": [5e8, 5e8]}))
    assert sp.MagicFormulaSpec().is_satisfied_by(big)                                        # ROIC 26.7 %, EY 12.9 %
    assert not sp.MagicFormulaSpec(min_roic=30).is_satisfied_by(big)
    assert not sp.MagicFormulaSpec().is_satisfied_by(magic_candidate(sector="Banking"))


def test_magic_formula_spec_requires_positive_book_value_earnings_and_size():
    big_inc = fin({"EBIT": [4e8, 3e8], "Net Income": [2.5e8, 2e8]})
    big_bal = fin({"Total Assets": [2e9, 2e9], "Current Liabilities": [5e8, 5e8]})
    mk = lambda **o: magic_candidate(income_stmt=big_inc, balance_sheet=big_bal, **o)
    spec = sp.MagicFormulaSpec()
    assert spec.is_satisfied_by(mk())
    assert not spec.is_satisfied_by(mk(book_value=0.0)) and not spec.is_satisfied_by(mk(book_value=None))
    assert not spec.is_satisfied_by(mk(book_value=-1.0))
    loss = fin({"EBIT": [4e8, 3e8], "Net Income": [-1.0, 2e8]})
    assert not spec.is_satisfied_by(magic_candidate(income_stmt=loss, balance_sheet=big_bal))
    assert not spec.is_satisfied_by(mk(market_cap=1e9))                       # 100 Cr is not > 100 Cr
    assert not spec.is_satisfied_by(cand())
    assert "Magic Formula" in spec.explain()


def quarterly(rev, ni):
    return pd.DataFrame({str(i): [r, n] for i, (r, n) in enumerate(zip(rev, ni))},
                        index=["Total Revenue", "Net Income"])


def test_bull_cartel_spec_thresholds():
    spec = sp.BullCartelSpec()
    good = quarterly([120, 0, 0, 0, 100], [3e7, 0, 0, 0, 2e7])         # sales +20 %, profit +50 %, NP 3 Cr
    assert spec.is_satisfied_by(cand(quarterly_inc=good))
    assert not spec.is_satisfied_by(cand(quarterly_inc=quarterly([115, 0, 0, 0, 100], [3e7, 0, 0, 0, 2e7])))   # =15 %
    assert spec.is_satisfied_by(cand(quarterly_inc=quarterly([115.1, 0, 0, 0, 100], [3e7, 0, 0, 0, 2e7])))
    assert not spec.is_satisfied_by(cand(quarterly_inc=quarterly([120, 0, 0, 0, 100], [2.4e7, 0, 0, 0, 2e7])))  # 20 %
    assert not spec.is_satisfied_by(cand(quarterly_inc=quarterly([120, 0, 0, 0, 100], [1e7, 0, 0, 0, 0.5e7])))  # NP 1 Cr
    assert not spec.is_satisfied_by(cand())
    assert not spec.is_satisfied_by(cand(quarterly_inc=quarterly([120, 0, 0, 0], [3e7, 0, 0, 0])))             # 4 quarters
    assert "Bull Cartel" in spec.explain()


def test_bull_cartel_uses_absolute_base_for_loss_making_comparison_quarter():
    # prior-year loss of -10 -> profit 10: growth = (10 - -10)/10 = 200 %
    inc = quarterly([120, 0, 0, 0, 100], [2e7, 0, 0, 0, -2e7])
    assert sp.BullCartelSpec().is_satisfied_by(cand(quarterly_inc=inc))


def test_triple_hit_requires_all_three_sub_specs():
    t = sp.TripleHitSpec()
    assert not t.is_satisfied_by(cand())
    t._darvas, t._piotroski, t._coffee = Const(True), Const(True), Const(True)
    assert t.is_satisfied_by(cand())
    for i, name in enumerate(("_darvas", "_piotroski", "_coffee")):
        specs = [Const(True), Const(True), Const(True)]
        specs[i] = Const(False)
        t._darvas, t._piotroski, t._coffee = specs
        assert not t.is_satisfied_by(cand()), name
    assert "Triple Hit" in t.explain()


@pytest.mark.parametrize("passes, min_screens, expected", [(3, 3, True), (2, 3, False), (6, 3, True),
                                                           (0, 0, True), (1, 2, False)])
def test_multi_screen_counts_passed_specs(passes, min_screens, expected):
    m = sp.MultiScreenSpec(min_screens=min_screens)
    m._specs = [Const(i < passes) for i in range(6)]
    assert m.is_satisfied_by(cand()) is expected
    assert m.passed_screeners(cand()) == [s.explain()[:20] for s in m._specs if s.v]
    assert f"≥{min_screens}" in m.explain()


def test_multi_screen_default_has_six_real_specs():
    m = sp.MultiScreenSpec()
    assert m.min_screens == 3 and len(m._specs) == 6
    assert not m.is_satisfied_by(cand())                    # an empty candidate passes nothing


def test_regime_sideways_band_edge_is_inclusive():
    # dma_period=2: DMA of the last two closes (98, 102) is 100, so pct_from is exactly +2.0
    idx = _index([100.0, 98.0, 102.0])
    assert idx.classify_regime(dma_period=2, slope_bars=1, sideways_pct=2.0) is MarketRegime.SIDEWAYS
    assert idx.classify_regime(dma_period=2, slope_bars=1, sideways_pct=1.99) is MarketRegime.BULL


def test_coffee_can_cagr_exactly_at_threshold_passes():
    inc = fin({"Total Revenue": [200.0, 100.0], "EBIT": [60.0, 45.0], "Net Income": [40.0, 30.0]})
    bal = fin({"Total Assets": [200.0, 180.0], "Current Liabilities": [50.0, 50.0]})
    c = cand(income_stmt=inc, balance_sheet=bal, market_cap=6e9, debt_to_equity=0.5)
    assert sp.CoffeeCanSpec(min_cagr=100.0).is_satisfied_by(c)          # CAGR is exactly 100.0
    assert not sp.CoffeeCanSpec(min_cagr=100.1).is_satisfied_by(c)


def test_coffee_can_debt_to_equity_of_exactly_ten_is_not_rescaled():
    assert not sp.CoffeeCanSpec().is_satisfied_by(coffee_candidate(debt_to_equity=10.0))     # treated as 10x
    assert sp.CoffeeCanSpec().is_satisfied_by(coffee_candidate(debt_to_equity=10.5))      # > 10: percent form


def test_golden_cross_is_evaluated_at_exactly_205_bars():
    spec = sp.GoldenCrossSpec()
    series = [100.0] * 160 + [90.0] * 45
    crossing = None
    for k in range(60):
        series.append(500.0)
        s = pd.Series(series)
        d50, d200 = s.rolling(50).mean(), s.rolling(200).mean()
        if d50.iloc[-2] < d200.iloc[-2] and d50.iloc[-1] > d200.iloc[-1]:
            crossing = pd.DataFrame({"Close": list(series)})
            break
    assert crossing is not None
    assert spec.is_satisfied_by(cand(ohlc_df=crossing, bar_count=205))
    assert not spec.is_satisfied_by(cand(ohlc_df=crossing, bar_count=204))
    assert sp.DMA50AboveDMA200Spec().is_satisfied_by(cand(ohlc_df=crossing, bar_count=205))
    assert not sp.DMA50AboveDMA200Spec().is_satisfied_by(cand(ohlc_df=crossing, bar_count=204))
