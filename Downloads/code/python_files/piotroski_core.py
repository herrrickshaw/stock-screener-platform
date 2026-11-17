"""
Shared Piotroski F-Score maths for the daily-report scripts.

``f_score_components`` turns yfinance annual statements into the nine 0/1
criteria plus the supporting ratios. The two reports differ only in how the
operating-cash-flow detail is scaled (Rs crore vs USD million), whether the
share count falls back to ``info['sharesOutstanding']`` and whether the share
count is echoed in the details, so those are parameters.
"""
from __future__ import annotations

from typing import Callable, Optional

INTERPRETATIONS = (
    (7, "STRONG — likely outperformer"),
    (4, "MODERATE — neutral stance"),
    (0, "WEAK — avoid or short candidate"),
)


def interpret(total: int) -> str:
    """Verdict text for an F-score (>=7 strong, >=4 moderate, else weak)."""
    return next(text for floor, text in INTERPRETATIONS if total >= floor)


def _ratio(a, b):
    return (a / b) if (a and b) else None


def _improved(curr, prev, higher_is_better: bool = True) -> int:
    """1 when both values exist and moved the right way, else 0."""
    if curr is None or prev is None:
        return 0
    return 1 if (curr > prev if higher_is_better else curr < prev) else 0


def f_score_components(
    inc, bal, cf, row: Callable,
    ocf_label: str, ocf_divisor: float, ocf_digits: int,
    shares_fallback: Optional[float] = None, echo_shares: bool = False,
) -> tuple[dict, dict]:
    """Return ``(scores, details)`` for the nine Piotroski criteria."""
    scores: dict = {}
    details: dict = {}

    # Profitability
    net_inc_0, assets_0 = row(inc, "Net Income", col=0), row(bal, "Total Assets", col=0)
    net_inc_1, assets_1 = row(inc, "Net Income", col=1), row(bal, "Total Assets", col=1)
    roa_0, roa_1 = _ratio(net_inc_0, assets_0), _ratio(net_inc_1, assets_1)

    scores["F1_ROA_positive"] = 1 if (roa_0 and roa_0 > 0) else 0
    details["ROA_current_%"] = round(roa_0 * 100, 2) if roa_0 else "N/A"

    ocf_0 = row(cf, "Operating Cash Flow", "Total Cash From Operating Activities", col=0)
    scores["F2_OCF_positive"] = 1 if (ocf_0 and ocf_0 > 0) else 0
    details[ocf_label] = round(ocf_0 / ocf_divisor, ocf_digits) if ocf_0 else "N/A"

    scores["F3_ROA_improving"] = _improved(roa_0, roa_1)
    details["ROA_prev_%"] = round(roa_1 * 100, 2) if roa_1 else "N/A"

    scores["F4_Accruals"] = 1 if (ocf_0 and assets_0 and roa_0 is not None and (ocf_0 / assets_0) > roa_0) else 0

    # Leverage & liquidity
    ltd_0 = row(bal, "Long Term Debt", col=0) or 0
    ltd_1 = row(bal, "Long Term Debt", col=1) or 0
    lev_0 = (ltd_0 / assets_0) if assets_0 else None
    lev_1 = (ltd_1 / assets_1) if assets_1 else None
    scores["F5_Leverage_down"] = _improved(lev_0, lev_1, higher_is_better=False)
    details["LTD_ratio_curr_%"] = round(lev_0 * 100, 2) if lev_0 else "N/A"
    details["LTD_ratio_prev_%"] = round(lev_1 * 100, 2) if lev_1 else "N/A"

    ca = ("Current Assets", "Total Current Assets")
    cl = ("Current Liabilities", "Total Current Liabilities")
    cr_0 = _ratio(row(bal, *ca, col=0), row(bal, *cl, col=0))
    cr_1 = _ratio(row(bal, *ca, col=1), row(bal, *cl, col=1))
    scores["F6_CurrentRatio_up"] = _improved(cr_0, cr_1)
    details["CurrentRatio_curr"] = round(cr_0, 2) if cr_0 else "N/A"
    details["CurrentRatio_prev"] = round(cr_1, 2) if cr_1 else "N/A"

    sh_0 = row(bal, "Share Issued", col=0) or shares_fallback
    sh_1 = row(bal, "Share Issued", col=1)
    # assume no dilution when data is absent
    scores["F7_No_dilution"] = (1 if sh_0 <= sh_1 else 0) if (sh_0 and sh_1) else 1
    if echo_shares:
        details["Shares_curr_M"] = round(sh_0 / 1e6, 1) if sh_0 else "N/A"

    # Operating efficiency
    rev_0, gp_0 = row(inc, "Total Revenue", col=0), row(inc, "Gross Profit", col=0)
    rev_1, gp_1 = row(inc, "Total Revenue", col=1), row(inc, "Gross Profit", col=1)
    gm_0, gm_1 = _ratio(gp_0, rev_0), _ratio(gp_1, rev_1)
    scores["F8_GrossMargin_up"] = _improved(gm_0, gm_1)
    details["GrossMargin_curr_%"] = round(gm_0 * 100, 2) if gm_0 else "N/A"
    details["GrossMargin_prev_%"] = round(gm_1 * 100, 2) if gm_1 else "N/A"

    at_0, at_1 = _ratio(rev_0, assets_0), _ratio(rev_1, assets_1)
    scores["F9_AssetTurnover_up"] = _improved(at_0, at_1)
    details["AssetTurnover_curr"] = round(at_0, 3) if at_0 else "N/A"
    details["AssetTurnover_prev"] = round(at_1, 3) if at_1 else "N/A"

    return scores, details
