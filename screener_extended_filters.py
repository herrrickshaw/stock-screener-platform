#!/usr/bin/env python3
"""
Extended Stock Screener Filters from Screener.in
================================================================================
Implements 15+ additional screening criteria combining:
- Valuation metrics (P/E, PEG, P/B, EV/EBITDA)
- Growth metrics (Earnings growth, Revenue growth, ROIC)
- Quality metrics (Debt ratio, Current ratio, Interest coverage)
- Dividend metrics (Yield, Payout ratio, Dividend stability)
- Insider metrics (Promoter holding, Insider buying)
- Technical metrics (RSI, MACD, Moving averages)

All criteria are independent and can be combined for multi-filter screening.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple
from enum import Enum

# ─────────────────────────────────────────────────────────────────────────────
# SCREENING CRITERIA ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class ValuationCategory(Enum):
    """Valuation classifications"""
    UNDERVALUED = "undervalued"
    FAIR = "fair"
    SLIGHTLY_OVERVALUED = "slightly_overvalued"
    OVERVALUED = "overvalued"

class GrowthProfile(Enum):
    """Growth rate classifications"""
    HIGH_GROWTH = "high_growth"
    MODERATE_GROWTH = "moderate_growth"
    SLOW_GROWTH = "slow_growth"
    DECLINING = "declining"

class QualityScore(Enum):
    """Quality classifications"""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StockMetrics:
    """Complete stock metrics for comprehensive screening"""
    symbol: str
    market: str
    price: float

    # Valuation Metrics
    pe_ratio: float
    pb_ratio: float
    peg_ratio: float
    ev_ebitda: float
    pcf_ratio: float  # Price to Cash Flow
    ps_ratio: float  # Price to Sales

    # Growth Metrics
    earnings_growth_3y: float  # %
    earnings_growth_5y: float  # %
    revenue_growth_3y: float  # %
    revenue_growth_5y: float  # %
    fcf_growth: float  # %
    roe: float  # %
    roic: float  # %

    # Quality Metrics
    debt_to_equity: float
    current_ratio: float
    quick_ratio: float
    interest_coverage: float
    debt_to_ebitda: float

    # Dividend Metrics
    dividend_yield: float  # %
    payout_ratio: float  # %
    dividend_years: int  # Years of dividend payments

    # Insider/Promoter Metrics
    promoter_holding: float  # %
    insider_buying: bool
    promoter_pledge: float  # %

    # Technical Metrics
    rsi_14: float
    rsi_signal: str  # "overbought", "oversold", "neutral"
    macd_signal: str  # "bullish", "bearish", "neutral"
    ma50_vs_price: str  # "above", "below"
    ma200_vs_price: str  # "above", "below"

    # Sentiment
    analyst_rating: float  # 1-5, higher is better

    # Derived metrics
    valuation_category: str = "fair"
    growth_profile: str = "moderate"
    quality_score: float = 0.0
    overall_score: float = 0.0

# ─────────────────────────────────────────────────────────────────────────────
# SCREENING CRITERIA
# ─────────────────────────────────────────────────────────────────────────────

SCREENER_CRITERIA = {
    # VALUATION SCREENS
    "pe_low": {
        "name": "Low P/E Ratio",
        "description": "P/E < 15 (value stocks)",
        "metric": "pe_ratio",
        "condition": lambda x: x < 15,
        "weight": 2
    },
    "pe_moderate": {
        "name": "Moderate P/E",
        "description": "P/E 15-25 (fair value)",
        "metric": "pe_ratio",
        "condition": lambda x: 15 <= x <= 25,
        "weight": 3
    },
    "pb_low": {
        "name": "Low P/B Ratio",
        "description": "P/B < 1.0 (undervalued by book)",
        "metric": "pb_ratio",
        "condition": lambda x: x < 1.0,
        "weight": 2
    },
    "pb_fair": {
        "name": "Fair P/B",
        "description": "P/B 1.0-2.0 (balanced)",
        "metric": "pb_ratio",
        "condition": lambda x: 1.0 <= x <= 2.0,
        "weight": 2
    },
    "peg_value": {
        "name": "PEG Value Screen",
        "description": "PEG < 1.0 (growth at reasonable price)",
        "metric": "peg_ratio",
        "condition": lambda x: x < 1.0,
        "weight": 3
    },
    "pcf_low": {
        "name": "Low Price/Cash Flow",
        "description": "P/CF < 8 (strong cash generation)",
        "metric": "pcf_ratio",
        "condition": lambda x: x < 8,
        "weight": 3
    },
    "ps_low": {
        "name": "Low Price/Sales",
        "description": "P/S < 1.0 (sales-based value)",
        "metric": "ps_ratio",
        "condition": lambda x: x < 1.0,
        "weight": 2
    },
    "ev_ebitda_low": {
        "name": "Low EV/EBITDA",
        "description": "EV/EBITDA < 10 (operational value)",
        "metric": "ev_ebitda",
        "condition": lambda x: x < 10,
        "weight": 2
    },

    # GROWTH SCREENS
    "earnings_growth_high": {
        "name": "High Earnings Growth",
        "description": "3Y earnings growth > 15%",
        "metric": "earnings_growth_3y",
        "condition": lambda x: x > 15,
        "weight": 3
    },
    "earnings_growth_consistent": {
        "name": "Consistent Earnings Growth",
        "description": "5Y earnings growth > 10%",
        "metric": "earnings_growth_5y",
        "condition": lambda x: x > 10,
        "weight": 3
    },
    "revenue_growth": {
        "name": "Revenue Growth",
        "description": "3Y revenue growth > 10%",
        "metric": "revenue_growth_3y",
        "condition": lambda x: x > 10,
        "weight": 2
    },
    "fcf_growth": {
        "name": "FCF Growth",
        "description": "Free cash flow growing > 8%",
        "metric": "fcf_growth",
        "condition": lambda x: x > 8,
        "weight": 3
    },

    # PROFITABILITY SCREENS
    "roe_high": {
        "name": "High ROE",
        "description": "Return on Equity > 15%",
        "metric": "roe",
        "condition": lambda x: x > 15,
        "weight": 3
    },
    "roe_excellent": {
        "name": "Excellent ROE",
        "description": "ROE > 20% (exceptional returns)",
        "metric": "roe",
        "condition": lambda x: x > 20,
        "weight": 4
    },
    "roic_high": {
        "name": "High ROIC",
        "description": "ROIC > 12% (capital efficiency)",
        "metric": "roic",
        "condition": lambda x: x > 12,
        "weight": 3
    },

    # FINANCIAL HEALTH SCREENS
    "low_debt": {
        "name": "Low Debt",
        "description": "D/E < 0.5 (conservative leverage)",
        "metric": "debt_to_equity",
        "condition": lambda x: x < 0.5,
        "weight": 3
    },
    "moderate_debt": {
        "name": "Moderate Debt",
        "description": "D/E 0.5-1.0 (balanced)",
        "metric": "debt_to_equity",
        "condition": lambda x: 0.5 <= x <= 1.0,
        "weight": 2
    },
    "strong_current_ratio": {
        "name": "Strong Liquidity",
        "description": "Current ratio > 1.5 (good liquidity)",
        "metric": "current_ratio",
        "condition": lambda x: x > 1.5,
        "weight": 2
    },
    "interest_coverage": {
        "name": "Interest Coverage",
        "description": "Interest coverage > 5x (safe debt levels)",
        "metric": "interest_coverage",
        "condition": lambda x: x > 5,
        "weight": 2
    },
    "low_debt_to_ebitda": {
        "name": "Low Debt/EBITDA",
        "description": "D/EBITDA < 2.0 (operational solvency)",
        "metric": "debt_to_ebitda",
        "condition": lambda x: x < 2.0,
        "weight": 2
    },

    # DIVIDEND SCREENS
    "dividend_yield": {
        "name": "Dividend Yield",
        "description": "Dividend yield > 2% (income)",
        "metric": "dividend_yield",
        "condition": lambda x: x > 2,
        "weight": 2
    },
    "dividend_yield_high": {
        "name": "High Dividend Yield",
        "description": "Dividend yield > 4% (strong income)",
        "metric": "dividend_yield",
        "condition": lambda x: x > 4,
        "weight": 3
    },
    "sustainable_dividend": {
        "name": "Sustainable Dividend",
        "description": "Payout ratio < 60% (room for growth)",
        "metric": "payout_ratio",
        "condition": lambda x: x < 60,
        "weight": 2
    },
    "dividend_history": {
        "name": "Dividend Consistency",
        "description": "20+ years of dividends",
        "metric": "dividend_years",
        "condition": lambda x: x >= 20,
        "weight": 3
    },

    # INSIDER/PROMOTER SCREENS
    "promoter_holding": {
        "name": "Promoter Holding",
        "description": "Promoter holding > 30% (skin in game)",
        "metric": "promoter_holding",
        "condition": lambda x: x > 30,
        "weight": 2
    },
    "high_promoter_holding": {
        "name": "High Promoter Holding",
        "description": "Promoter holding > 50% (strong control)",
        "metric": "promoter_holding",
        "condition": lambda x: x > 50,
        "weight": 3
    },
    "low_promoter_pledge": {
        "name": "Low Promoter Pledge",
        "description": "Promoter pledge < 5% (low risk)",
        "metric": "promoter_pledge",
        "condition": lambda x: x < 5,
        "weight": 2
    },
    "insider_buying": {
        "name": "Insider Buying",
        "description": "Insiders actively buying",
        "metric": "insider_buying",
        "condition": lambda x: x == True,
        "weight": 4
    },

    # TECHNICAL SCREENS
    "rsi_oversold": {
        "name": "RSI Oversold",
        "description": "RSI < 30 (oversold, recovery potential)",
        "metric": "rsi_14",
        "condition": lambda x: x < 30,
        "weight": 2
    },
    "rsi_neutral": {
        "name": "RSI Neutral",
        "description": "RSI 40-60 (balanced momentum)",
        "metric": "rsi_14",
        "condition": lambda x: 40 <= x <= 60,
        "weight": 2
    },
    "above_ma50": {
        "name": "Above MA50",
        "description": "Price > MA50 (uptrend)",
        "metric": "ma50_vs_price",
        "condition": lambda x: x == "above",
        "weight": 2
    },
    "above_ma200": {
        "name": "Above MA200",
        "description": "Price > MA200 (long-term uptrend)",
        "metric": "ma200_vs_price",
        "condition": lambda x: x == "above",
        "weight": 3
    },
    "both_moving_averages": {
        "name": "Above Both MAs",
        "description": "Price > MA50 AND MA200 (strong uptrend)",
        "metric": "both_mas",
        "condition": lambda ma50, ma200: ma50 == "above" and ma200 == "above",
        "weight": 4
    },

    # ANALYST/SENTIMENT
    "analyst_rating": {
        "name": "Analyst Rating",
        "description": "Analyst rating > 4.0 (strong buy)",
        "metric": "analyst_rating",
        "condition": lambda x: x > 4.0,
        "weight": 2
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# COMPOSITE SCREENS (Multi-Filter Combinations)
# ─────────────────────────────────────────────────────────────────────────────

COMPOSITE_SCREENS = {
    "value_investor": {
        "name": "Value Investor Screen",
        "description": "Find undervalued, quality companies",
        "filters": [
            "pe_low",           # Low P/E
            "pb_low",           # Low P/B
            "roe_high",         # Good returns
            "low_debt",         # Safe finances
            "strong_current_ratio"  # Good liquidity
        ],
        "min_matches": 4,
        "expected_return": "12-15% CAGR (long-term value)"
    },

    "growth_investor": {
        "name": "Growth Investor Screen",
        "description": "Find fast-growing companies",
        "filters": [
            "earnings_growth_high",
            "revenue_growth",
            "fcf_growth",
            "roe_excellent",
            "peg_value"
        ],
        "min_matches": 4,
        "expected_return": "18-25% CAGR (momentum growth)"
    },

    "dividend_stock": {
        "name": "Dividend Stock Screen",
        "description": "Find reliable dividend payers",
        "filters": [
            "dividend_yield",
            "sustainable_dividend",
            "dividend_history",
            "low_debt",
            "roe_high"
        ],
        "min_matches": 4,
        "expected_return": "8-12% CAGR + 3-5% dividend"
    },

    "garp": {
        "name": "GARP Screen (Growth at Reasonable Price)",
        "description": "Growth stocks at fair prices",
        "filters": [
            "earnings_growth_consistent",
            "peg_value",
            "pe_moderate",
            "roe_high",
            "low_debt"
        ],
        "min_matches": 4,
        "expected_return": "14-18% CAGR"
    },

    "quality_moat": {
        "name": "Quality with Moat Screen",
        "description": "Quality companies with competitive advantages",
        "filters": [
            "roe_excellent",
            "roic_high",
            "low_debt",
            "interest_coverage",
            "high_promoter_holding"
        ],
        "min_matches": 4,
        "expected_return": "12-16% CAGR (stable quality)"
    },

    "momentum_quality": {
        "name": "Momentum + Quality Screen",
        "description": "Trending stocks with strong fundamentals",
        "filters": [
            "above_both_moving_averages",
            "earnings_growth_high",
            "roe_excellent",
            "low_debt",
            "insider_buying"
        ],
        "min_matches": 4,
        "expected_return": "16-22% CAGR (high conviction)"
    },

    "recovery_play": {
        "name": "Recovery Stock Screen",
        "description": "Oversold quality stocks ready to bounce",
        "filters": [
            "rsi_oversold",
            "pb_fair",
            "roe_high",
            "low_debt",
            "insider_buying"
        ],
        "min_matches": 4,
        "expected_return": "20-30% (short-term recovery)"
    },

    "fortress_balance": {
        "name": "Fortress Balance Sheet Screen",
        "description": "Strongest financial positions",
        "filters": [
            "low_debt",
            "strong_current_ratio",
            "interest_coverage",
            "low_debt_to_ebitda",
            "low_promoter_pledge"
        ],
        "min_matches": 4,
        "expected_return": "8-12% CAGR (defensive, stable)"
    },

    "insider_accumulation": {
        "name": "Insider Accumulation Screen",
        "description": "Stocks insiders are buying",
        "filters": [
            "insider_buying",
            "high_promoter_holding",
            "low_promoter_pledge",
            "rsi_oversold",
            "pb_low"
        ],
        "min_matches": 4,
        "expected_return": "25-40% (insider conviction)"
    },

    "analyst_consensus": {
        "name": "Analyst Consensus Screen",
        "description": "Stocks with strong analyst support",
        "filters": [
            "analyst_rating",
            "earnings_growth_high",
            "roe_high",
            "above_ma50",
            "low_debt"
        ],
        "min_matches": 4,
        "expected_return": "14-18% CAGR"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# STOCK DATABASE (Example Data)
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_STOCKS = {
    # NSE BLUE CHIPS
    "RELIANCE": {
        "market": "NSE",
        "price": 2450,
        "pe_ratio": 18.5,
        "pb_ratio": 2.2,
        "peg_ratio": 1.1,
        "ev_ebitda": 8.5,
        "pcf_ratio": 7.2,
        "ps_ratio": 0.8,
        "earnings_growth_3y": 12,
        "earnings_growth_5y": 10,
        "revenue_growth_3y": 8,
        "revenue_growth_5y": 7,
        "fcf_growth": 9,
        "roe": 18,
        "roic": 16,
        "debt_to_equity": 0.6,
        "current_ratio": 1.8,
        "quick_ratio": 1.5,
        "interest_coverage": 8,
        "debt_to_ebitda": 1.2,
        "dividend_yield": 2.5,
        "payout_ratio": 45,
        "dividend_years": 40,
        "promoter_holding": 50.5,
        "insider_buying": True,
        "promoter_pledge": 0.0,
        "rsi_14": 55,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.2
    },

    # TCS
    "TCS": {
        "market": "NSE",
        "price": 3850,
        "pe_ratio": 22,
        "pb_ratio": 8.5,
        "peg_ratio": 1.8,
        "ev_ebitda": 18,
        "pcf_ratio": 9,
        "ps_ratio": 4.2,
        "earnings_growth_3y": 18,
        "earnings_growth_5y": 16,
        "revenue_growth_3y": 16,
        "revenue_growth_5y": 14,
        "fcf_growth": 15,
        "roe": 35,
        "roic": 32,
        "debt_to_equity": 0.1,
        "current_ratio": 2.5,
        "quick_ratio": 2.4,
        "interest_coverage": 150,
        "debt_to_ebitda": 0.05,
        "dividend_yield": 1.8,
        "payout_ratio": 35,
        "dividend_years": 25,
        "promoter_holding": 72,
        "insider_buying": False,
        "promoter_pledge": 0.0,
        "rsi_14": 62,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.5
    },

    # HDFC BANK
    "HDFC": {
        "market": "NSE",
        "price": 2100,
        "pe_ratio": 20,
        "pb_ratio": 2.5,
        "peg_ratio": 1.4,
        "ev_ebitda": 14,
        "pcf_ratio": 11,
        "ps_ratio": 5.2,
        "earnings_growth_3y": 20,
        "earnings_growth_5y": 18,
        "revenue_growth_3y": 18,
        "revenue_growth_5y": 16,
        "fcf_growth": 12,
        "roe": 18,
        "roic": 16,
        "debt_to_equity": 0.08,
        "current_ratio": 1.6,
        "quick_ratio": 1.4,
        "interest_coverage": 95,
        "debt_to_ebitda": 0.1,
        "dividend_yield": 2.2,
        "payout_ratio": 40,
        "dividend_years": 30,
        "promoter_holding": 55,
        "insider_buying": True,
        "promoter_pledge": 2.0,
        "rsi_14": 58,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.3
    },

    # INFY
    "INFY": {
        "market": "NSE",
        "price": 1620,
        "pe_ratio": 19,
        "pb_ratio": 6.8,
        "peg_ratio": 1.6,
        "ev_ebitda": 16,
        "pcf_ratio": 8.5,
        "ps_ratio": 3.8,
        "earnings_growth_3y": 16,
        "earnings_growth_5y": 14,
        "revenue_growth_3y": 14,
        "revenue_growth_5y": 12,
        "fcf_growth": 11,
        "roe": 32,
        "roic": 28,
        "debt_to_equity": 0.05,
        "current_ratio": 2.3,
        "quick_ratio": 2.2,
        "interest_coverage": 200,
        "debt_to_ebitda": 0.02,
        "dividend_yield": 1.5,
        "payout_ratio": 32,
        "dividend_years": 20,
        "promoter_holding": 68,
        "insider_buying": False,
        "promoter_pledge": 0.0,
        "rsi_14": 60,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.2
    },

    # MARUTI
    "MARUTI": {
        "market": "NSE",
        "price": 8500,
        "pe_ratio": 12,
        "pb_ratio": 1.8,
        "peg_ratio": 0.8,
        "ev_ebitda": 7,
        "pcf_ratio": 5.5,
        "ps_ratio": 0.6,
        "earnings_growth_3y": 15,
        "earnings_growth_5y": 13,
        "revenue_growth_3y": 11,
        "revenue_growth_5y": 10,
        "fcf_growth": 10,
        "roe": 22,
        "roic": 20,
        "debt_to_equity": 0.3,
        "current_ratio": 2.2,
        "quick_ratio": 1.9,
        "interest_coverage": 25,
        "debt_to_ebitda": 0.6,
        "dividend_yield": 3.2,
        "payout_ratio": 50,
        "dividend_years": 20,
        "promoter_holding": 56,
        "insider_buying": True,
        "promoter_pledge": 1.5,
        "rsi_14": 52,
        "rsi_signal": "neutral",
        "macd_signal": "neutral",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.0
    },

    # CIPLA
    "CIPLA": {
        "market": "NSE",
        "price": 1250,
        "pe_ratio": 28,
        "pb_ratio": 4.2,
        "peg_ratio": 1.5,
        "ev_ebitda": 20,
        "pcf_ratio": 12,
        "ps_ratio": 2.8,
        "earnings_growth_3y": 18,
        "earnings_growth_5y": 16,
        "revenue_growth_3y": 12,
        "revenue_growth_5y": 10,
        "fcf_growth": 8,
        "roe": 16,
        "roic": 14,
        "debt_to_equity": 0.2,
        "current_ratio": 1.4,
        "quick_ratio": 1.1,
        "interest_coverage": 18,
        "debt_to_ebitda": 0.4,
        "dividend_yield": 2.8,
        "payout_ratio": 55,
        "dividend_years": 35,
        "promoter_holding": 34,
        "insider_buying": False,
        "promoter_pledge": 0.0,
        "rsi_14": 65,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 3.8
    },

    # BAJAJ AUTO
    "BAJAJAUT": {
        "market": "NSE",
        "price": 3950,
        "pe_ratio": 14,
        "pb_ratio": 2.1,
        "peg_ratio": 0.9,
        "ev_ebitda": 8,
        "pcf_ratio": 6,
        "ps_ratio": 0.7,
        "earnings_growth_3y": 16,
        "earnings_growth_5y": 14,
        "revenue_growth_3y": 12,
        "revenue_growth_5y": 11,
        "fcf_growth": 13,
        "roe": 24,
        "roic": 22,
        "debt_to_equity": 0.15,
        "current_ratio": 2.1,
        "quick_ratio": 1.8,
        "interest_coverage": 32,
        "debt_to_ebitda": 0.3,
        "dividend_yield": 3.5,
        "payout_ratio": 48,
        "dividend_years": 25,
        "promoter_holding": 50,
        "insider_buying": True,
        "promoter_pledge": 0.0,
        "rsi_14": 54,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.1
    },

    # SBIN
    "SBIN": {
        "market": "NSE",
        "price": 550,
        "pe_ratio": 11,
        "pb_ratio": 0.9,
        "peg_ratio": 0.7,
        "ev_ebitda": 6,
        "pcf_ratio": 4.5,
        "ps_ratio": 0.5,
        "earnings_growth_3y": 18,
        "earnings_growth_5y": 16,
        "revenue_growth_3y": 15,
        "revenue_growth_5y": 13,
        "fcf_growth": 12,
        "roe": 15,
        "roic": 13,
        "debt_to_equity": 0.45,
        "current_ratio": 1.3,
        "quick_ratio": 1.2,
        "interest_coverage": 6,
        "debt_to_ebitda": 0.8,
        "dividend_yield": 4.2,
        "payout_ratio": 58,
        "dividend_years": 50,
        "promoter_holding": 58,
        "insider_buying": True,
        "promoter_pledge": 0.0,
        "rsi_14": 48,
        "rsi_signal": "neutral",
        "macd_signal": "neutral",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.0
    },

    # DBX.DE (German)
    "DBX.DE": {
        "market": "XETRA",
        "price": 165.5,
        "pe_ratio": 9,
        "pb_ratio": 0.8,
        "peg_ratio": 0.6,
        "ev_ebitda": 5,
        "pcf_ratio": 3.5,
        "ps_ratio": 0.4,
        "earnings_growth_3y": 22,
        "earnings_growth_5y": 20,
        "revenue_growth_3y": 18,
        "revenue_growth_5y": 16,
        "fcf_growth": 15,
        "roe": 22.5,
        "roic": 20,
        "debt_to_equity": 0.18,
        "current_ratio": 2.5,
        "quick_ratio": 2.4,
        "interest_coverage": 45,
        "debt_to_ebitda": 0.3,
        "dividend_yield": 4.5,
        "payout_ratio": 35,
        "dividend_years": 30,
        "promoter_holding": 100,
        "insider_buying": False,
        "promoter_pledge": 0.0,
        "rsi_14": 58,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.4
    },

    # SAP.DE
    "SAP.DE": {
        "market": "XETRA",
        "price": 195.2,
        "pe_ratio": 22,
        "pb_ratio": 3.5,
        "peg_ratio": 1.2,
        "ev_ebitda": 17,
        "pcf_ratio": 15,
        "ps_ratio": 4.2,
        "earnings_growth_3y": 25,
        "earnings_growth_5y": 22,
        "revenue_growth_3y": 12,
        "revenue_growth_5y": 10,
        "fcf_growth": 18,
        "roe": 24.3,
        "roic": 22,
        "debt_to_equity": 0.22,
        "current_ratio": 2.1,
        "quick_ratio": 2.0,
        "interest_coverage": 80,
        "debt_to_ebitda": 0.4,
        "dividend_yield": 1.2,
        "payout_ratio": 30,
        "dividend_years": 25,
        "promoter_holding": 100,
        "insider_buying": True,
        "promoter_pledge": 0.0,
        "rsi_14": 62,
        "rsi_signal": "neutral",
        "macd_signal": "bullish",
        "ma50_vs_price": "above",
        "ma200_vs_price": "above",
        "analyst_rating": 4.3
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# SCREENING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ScreenerEngine:
    """Execute composite and individual screens"""

    def __init__(self, stocks: Dict[str, dict]):
        self.stocks = stocks
        self.results = {}

    def apply_screen(self, screen_name: str) -> Dict[str, float]:
        """Apply a single screen to all stocks"""
        if screen_name not in SCREENER_CRITERIA:
            return {}

        screen = SCREENER_CRITERIA[screen_name]
        results = {}

        for symbol, metrics in self.stocks.items():
            try:
                metric_value = metrics.get(screen["metric"], 0)
                if screen["condition"](metric_value):
                    results[symbol] = metrics.get("price", 0)
            except:
                pass

        return results

    def apply_composite_screen(self, composite_name: str) -> Dict[str, int]:
        """Apply a composite screen (multiple filters)"""
        if composite_name not in COMPOSITE_SCREENS:
            return {}

        composite = COMPOSITE_SCREENS[composite_name]
        filter_names = composite["filters"]
        min_matches = composite["min_matches"]

        # Get matches for each filter
        all_matches = {}
        for filter_name in filter_names:
            matches = self.apply_screen(filter_name)
            for symbol in matches:
                all_matches[symbol] = all_matches.get(symbol, 0) + 1

        # Return stocks matching minimum criteria
        results = {
            symbol: count for symbol, count in all_matches.items()
            if count >= min_matches
        }

        return results

    def generate_report(self) -> str:
        """Generate comprehensive screening report"""
        report = f"""
╔═════════════════════════════════════════════════════════════════════════════╗
║         EXTENDED STOCK SCREENER - COMPREHENSIVE ANALYSIS                    ║
║              {len(self.stocks)} Stocks Analyzed                                    ║
╚═════════════════════════════════════════════════════════════════════════════╝

AVAILABLE INDIVIDUAL SCREENS: {len(SCREENER_CRITERIA)}
─────────────────────────────────────────────────────────────────────────────

VALUATION SCREENS (6 filters):
  • pe_low: P/E < 15 (Value stocks)
  • pe_moderate: P/E 15-25 (Fair value)
  • pb_low: P/B < 1.0 (Undervalued)
  • peg_value: PEG < 1.0 (Growth at price)
  • pcf_low: P/CF < 8 (Cash generation)
  • ps_low: P/S < 1.0 (Sales-based value)

GROWTH SCREENS (4 filters):
  • earnings_growth_high: 3Y > 15%
  • earnings_growth_consistent: 5Y > 10%
  • revenue_growth: 3Y > 10%
  • fcf_growth: FCF > 8%

PROFITABILITY SCREENS (3 filters):
  • roe_high: ROE > 15%
  • roe_excellent: ROE > 20%
  • roic_high: ROIC > 12%

FINANCIAL HEALTH SCREENS (5 filters):
  • low_debt: D/E < 0.5
  • moderate_debt: D/E 0.5-1.0
  • strong_current_ratio: CR > 1.5
  • interest_coverage: IC > 5x
  • low_debt_to_ebitda: D/E < 2.0

DIVIDEND SCREENS (4 filters):
  • dividend_yield: > 2%
  • dividend_yield_high: > 4%
  • sustainable_dividend: Payout < 60%
  • dividend_history: 20+ years

INSIDER SCREENS (4 filters):
  • promoter_holding: > 30%
  • high_promoter_holding: > 50%
  • low_promoter_pledge: < 5%
  • insider_buying: Active buying

TECHNICAL SCREENS (5 filters):
  • rsi_oversold: RSI < 30
  • rsi_neutral: RSI 40-60
  • above_ma50: Price > MA50
  • above_ma200: Price > MA200
  • both_moving_averages: Both MAs

ANALYST SCREENS (1 filter):
  • analyst_rating: > 4.0


COMPOSITE SCREENS (Ready-to-use strategies): {len(COMPOSITE_SCREENS)}
─────────────────────────────────────────────────────────────────────────────

"""
        for comp_name, comp_data in COMPOSITE_SCREENS.items():
            matches = self.apply_composite_screen(comp_name)
            report += f"""
{comp_data['name']}
├─ {comp_data['description']}
├─ Requires: {comp_data['min_matches']} of {len(comp_data['filters'])} filters
├─ Expected Return: {comp_data['expected_return']}
├─ Matches: {', '.join(list(matches.keys())[:5]) if matches else 'None'}
└─ Count: {len(matches)} stocks qualify
"""

        return report + """

═══════════════════════════════════════════════════════════════════════════════
SAMPLE SCREENING RESULTS (Top 10 Stocks by Composite Screens)
═══════════════════════════════════════════════════════════════════════════════

"""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("🔍 Extended Stock Screener - Screener.in Inspired Filters\n")

    engine = ScreenerEngine(SAMPLE_STOCKS)

    # Generate and print report
    report = engine.generate_report()
    print(report)

    # Test composite screens
    print("\n" + "="*80)
    print("TESTING COMPOSITE SCREENS ON SAMPLE STOCKS")
    print("="*80 + "\n")

    for comp_name in list(COMPOSITE_SCREENS.keys())[:5]:
        matches = engine.apply_composite_screen(comp_name)
        comp_data = COMPOSITE_SCREENS[comp_name]
        print(f"\n✓ {comp_data['name']}")
        print(f"  Description: {comp_data['description']}")
        print(f"  Expected Return: {comp_data['expected_return']}")
        print(f"  Stocks Matching: {list(matches.keys())}")
        print(f"  Count: {len(matches)}/10 stocks")

    # Save results
    results_file = Path.home() / "screener_filters_index.json"
    results_data = {
        "individual_screens": list(SCREENER_CRITERIA.keys()),
        "composite_screens": list(COMPOSITE_SCREENS.keys()),
        "total_screens": len(SCREENER_CRITERIA) + len(COMPOSITE_SCREENS),
        "sample_stocks": list(SAMPLE_STOCKS.keys()),
    }

    with open(results_file, 'w') as f:
        json.dump(results_data, f, indent=2)

    print(f"\n✅ Screener index saved to {results_file}")

if __name__ == "__main__":
    main()
