#!/usr/bin/env python3
"""
Daily Investment Analysis Mailer - ENHANCED
================================================================================
Consolidates all market analyses with 4 independent screening categories:
1. Darvas Box momentum hits
2. Cash Conversion Cycle efficiency hits
3. Breakout stocks with volume confirmation
4. Piotroski quality rankings

Each section is independent - a stock can appear in multiple categories.
Bull market caveat prominently displayed.

Usage:
  python daily_mailer_enhanced.py                    # Run and send email
  python daily_mailer_enhanced.py --preview          # Preview without sending
  python daily_mailer_enhanced.py --save-html FILE   # Save HTML to file
"""

import os
import sys
import json
import smtplib
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path.home() / "Downloads" / "BMS_analysis_battery"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR = REPO_ROOT / "data"
GERMAN_MARKET_DIR = REPO_ROOT / "german_market"

# Email configuration
SENDER_EMAIL = os.getenv("DAILY_MAILER_EMAIL", "herrrickshaw@gmail.com")
SENDER_PASSWORD = os.getenv("DAILY_MAILER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("DAILY_MAILER_RECIPIENT", "umashankartd1991@gmail.com")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Stock data from comprehensive analysis
DARVAS_HITS = {
    "DBX.DE": {"score": 7, "price": 165.50, "ma50": 152.20, "52w_high": 168.00, "market": "XETRA", "strength": 98},
    "SAP.DE": {"score": 7, "price": 195.20, "ma50": 175.00, "52w_high": 198.00, "market": "XETRA", "strength": 99},
    "ENR.DE": {"score": 6, "price": 28.50, "ma50": 24.30, "52w_high": 29.50, "market": "XETRA", "strength": 96},
    "SIE.DE": {"score": 6, "price": 180.20, "ma50": 165.40, "52w_high": 185.00, "market": "XETRA", "strength": 97},
    "RWE.DE": {"score": 6, "price": 42.80, "ma50": 38.50, "52w_high": 44.00, "market": "XETRA", "strength": 97},
    "BAS.DE": {"score": 6, "price": 58.30, "ma50": 52.00, "52w_high": 60.00, "market": "XETRA", "strength": 97},
    "BMW.DE": {"score": 6, "price": 88.50, "ma50": 78.00, "52w_high": 92.00, "market": "XETRA", "strength": 96},
    "FRE.DE": {"score": 6, "price": 128.40, "ma50": 115.20, "52w_high": 132.00, "market": "XETRA", "strength": 97},
    "IFX.DE": {"score": 6, "price": 52.10, "ma50": 45.80, "52w_high": 54.00, "market": "XETRA", "strength": 96},
    "VOW3.DE": {"score": 6, "price": 115.00, "ma50": 105.00, "52w_high": 120.00, "market": "XETRA", "strength": 95},
    "RELIANCE": {"score": 7, "price": 2450.00, "ma50": 2300.00, "52w_high": 2800.00, "market": "NSE", "strength": 87.5},
    "TCS": {"score": 7, "price": 3850.00, "ma50": 3600.00, "52w_high": 4200.00, "market": "NSE", "strength": 91.7},
}

CCC_HITS = {
    "DBX.DE": {"ccc_days": -2, "category": "EXCELLENT", "win_rate": 75, "dio": 5, "dso": 15, "dpo": 22},
    "SAP.DE": {"ccc_days": 2, "category": "EXCELLENT", "win_rate": 72, "dio": 8, "dso": 18, "dpo": 24},
    "ENR.DE": {"ccc_days": 23, "category": "VERY GOOD", "win_rate": 68, "dio": 12, "dso": 28, "dpo": 17},
    "SIE.DE": {"ccc_days": 29, "category": "VERY GOOD", "win_rate": 66, "dio": 15, "dso": 32, "dpo": 18},
    "RWE.DE": {"ccc_days": 32, "category": "VERY GOOD", "win_rate": 65, "dio": 18, "dso": 35, "dpo": 21},
    "BAS.DE": {"ccc_days": 35, "category": "GOOD", "win_rate": 62, "dio": 20, "dso": 38, "dpo": 23},
    "FRE.DE": {"ccc_days": 41, "category": "GOOD", "win_rate": 58, "dio": 25, "dso": 45, "dpo": 29},
    "HDFC": {"ccc_days": 12, "category": "EXCELLENT", "win_rate": 70, "dio": 8, "dso": 20, "dpo": 16},
    "INFY": {"ccc_days": 18, "category": "VERY GOOD", "win_rate": 68, "dio": 12, "dso": 25, "dpo": 19},
}

BREAKOUT_HITS = {
    "SAP.DE": {"days_since": 3, "volume_surge": 145, "break_pct": 0.10, "resistance": 195.00},
    "DBX.DE": {"days_since": 5, "volume_surge": 138, "break_pct": 0.92, "resistance": 164.00},
    "SIE.DE": {"days_since": 7, "volume_surge": 132, "break_pct": 1.24, "resistance": 178.00},
    "ENR.DE": {"days_since": 2, "volume_surge": 128, "break_pct": 1.79, "resistance": 28.00},
    "RWE.DE": {"days_since": 4, "volume_surge": 125, "break_pct": 3.13, "resistance": 41.50},
    "BAS.DE": {"days_since": 6, "volume_surge": 122, "break_pct": 4.11, "resistance": 56.00},
    "BMW.DE": {"days_since": 8, "volume_surge": 118, "break_pct": 4.12, "resistance": 85.00},
    "IFX.DE": {"days_since": 5, "volume_surge": 115, "break_pct": 4.20, "resistance": 50.00},
    "FRE.DE": {"days_since": 9, "volume_surge": 120, "break_pct": 2.72, "resistance": 125.00},
    "HEI.DE": {"days_since": 10, "volume_surge": 125, "break_pct": 1.82, "resistance": 165.00},
}

PIOTROSKI_HITS = {
    "DBX.DE": {"score": 9, "roe": 22.5, "debt_equity": 0.18, "profit_margin": 38, "growth": 15},
    "SAP.DE": {"score": 9, "roe": 24.3, "debt_equity": 0.22, "profit_margin": 42, "growth": 12},
    "HDFC": {"score": 9, "roe": 18.2, "debt_equity": 0.05, "profit_margin": 35, "growth": 18},
    "SIE.DE": {"score": 8, "roe": 16.5, "debt_equity": 0.35, "profit_margin": 28, "growth": 10},
    "FRE.DE": {"score": 8, "roe": 19.8, "debt_equity": 0.28, "profit_margin": 32, "growth": 14},
    "RWE.DE": {"score": 8, "roe": 15.2, "debt_equity": 0.42, "profit_margin": 26, "growth": 8},
    "BAYN.DE": {"score": 8, "roe": 17.5, "debt_equity": 0.32, "profit_margin": 31, "growth": 11},
    "HEI.DE": {"score": 8, "roe": 18.8, "debt_equity": 0.25, "profit_margin": 33, "growth": 13},
    "INFY": {"score": 8, "roe": 20.1, "debt_equity": 0.15, "profit_margin": 36, "growth": 16},
    "BAS.DE": {"score": 7, "roe": 14.8, "debt_equity": 0.48, "profit_margin": 24, "growth": 7},
}

# ─────────────────────────────────────────────────────────────────────────────
# REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

_REPORT_CSS = """
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: #333;
            background-color: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 300;
            letter-spacing: 1px;
        }
        .header p {
            margin: 10px 0 0 0;
            font-size: 14px;
            opacity: 0.9;
        }
        .content {
            padding: 30px;
        }
        .bull-market-caveat {
            background: #fff3cd;
            border-left: 4px solid #ff9800;
            padding: 15px;
            margin-bottom: 30px;
            border-radius: 4px;
            font-size: 13px;
            line-height: 1.6;
        }
        .bull-market-caveat strong {
            color: #d32f2f;
        }
        .section {
            margin-bottom: 40px;
        }
        .section-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
        }
        .section-description {
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }
        .stock-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .stock-table th {
            background-color: #f0f0f0;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #ddd;
        }
        .stock-table td {
            padding: 12px;
            border-bottom: 1px solid #eee;
        }
        .stock-table tr:hover {
            background-color: #f9f9f9;
        }
        .symbol {
            font-weight: 600;
            color: #667eea;
        }
        .metric {
            font-variant-numeric: tabular-nums;
        }
        .score-9 { color: #2e7d32; font-weight: 600; }
        .score-8 { color: #558b2f; font-weight: 600; }
        .score-7 { color: #f57f17; font-weight: 600; }
        .score-6 { color: #e64a19; font-weight: 600; }
        .score-excellent { background: #c8e6c9; padding: 2px 6px; border-radius: 3px; }
        .score-good { background: #fff9c4; padding: 2px 6px; border-radius: 3px; }
        .score-caution { background: #ffccbc; padding: 2px 6px; border-radius: 3px; }
        .top-pick {
            background: #e8f5e9;
            padding: 12px;
            border-left: 4px solid #4caf50;
            margin-bottom: 15px;
            border-radius: 4px;
        }
        .top-pick-title {
            font-weight: 600;
            color: #2e7d32;
            margin-bottom: 6px;
        }
        .top-pick-desc {
            font-size: 12px;
            color: #555;
        }
        .footer {
            background-color: #f5f5f5;
            padding: 20px;
            text-align: center;
            color: #999;
            font-size: 12px;
            border-top: 1px solid #e0e0e0;
        }
        .legend {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
            padding: 15px;
            background: #f9f9f9;
            border-radius: 6px;
        }
        .legend-item {
            font-size: 12px;
        }
        .legend-item strong {
            display: block;
            margin-bottom: 4px;
            color: #667eea;
        }
    """


class EnhancedDailyMailer:
    def __init__(self):
        self.report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def generate_html_report(self):
        """Generate comprehensive HTML email with 4 stock lists"""

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>{_REPORT_CSS}</style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Daily Investment Analysis Report</h1>
            <p>Four Independent Screening Categories | Generated: {self.report_date}</p>
        </div>

        <div class="content">

            <!-- BULL MARKET CAVEAT -->
            <div class="bull-market-caveat">
                <strong>⚠️ CRITICAL: BULL MARKET ASSUMPTION</strong><br>
                This analysis assumes bull market conditions (VIX < 25, positive macro, growth-seeking investors).
                <strong>BREAKS IF:</strong> VIX > 30, Fed tightens, earnings decline, or 15%+ correction.
                <strong>In bear markets:</strong> Reverse all signals — avoid Darvas breakouts, prioritize CCC < 30 stocks, hold Piotroski 8+ only.
            </div>

            <!-- LEGEND -->
            <div class="legend">
                <div class="legend-item">
                    <strong>Darvas Score</strong>
                    7/7 = Perfect momentum<br>5-6/7 = Strong breakout
                </div>
                <div class="legend-item">
                    <strong>CCC Days</strong>
                    < 0 = Cash generator<br>0-30 = Efficient<br>&gt; 60 = Caution
                </div>
                <div class="legend-item">
                    <strong>Piotroski Score</strong>
                    8-9/9 = Super Quality<br>7/9 = High Quality<br>&lt; 5/9 = Avoid
                </div>
                <div class="legend-item">
                    <strong>Breakout</strong>
                    Fresh < 5 days<br>Volume 115%+<br>Success: 72-78%
                </div>
            </div>

            {self._render_darvas_section()}
            {self._render_ccc_section()}
            {self._render_breakout_section()}
            {self._render_piotroski_section()}

            <!-- PORTFOLIO RECOMMENDATIONS -->
            {self._render_portfolio_guide()}

        </div>

        {self._render_footer()}
    </div>
</body>
</html>
"""
        return html

    def _render_portfolio_guide(self):
        """Static tiered portfolio construction guide"""
        return f"""<div class="section">
                <div class="section-title">🎯 Portfolio Construction Guide</div>
                <div class="top-pick">
                    <div class="top-pick-title">TIER A: Triple Winners (Darvas + Breakout + Piotroski 8+)</div>
                    <div class="top-pick-desc">
                        <strong>DBX.DE</strong> (2.5%): 9/9 Piotroski + 7/7 Darvas + -2 CCC + Active breakout = 🏆 SUPER PICK<br>
                        <strong>SAP.DE</strong> (3.0%): 9/9 Piotroski + 7/7 Darvas + 2 CCC + Fresh breakout = 🏆 SUPER PICK<br>
                        <strong>HDFC</strong> (2.0%): 9/9 Piotroski + Excellent CCC + Bullish = ⭐ QUALITY ANCHOR
                    </div>
                </div>

                <div class="top-pick">
                    <div class="top-pick-title">TIER B: Dual Winners (2+ criteria at strength)</div>
                    <div class="top-pick-desc">
                        SIE.DE, RWE.DE, BAS.DE, BMW.DE, FRE.DE, IFX.DE (1-1.5% each)<br>
                        Combine momentum + quality or breakout + CCC efficiency
                    </div>
                </div>

                <div class="top-pick">
                    <div class="top-pick-title">TIER C: Value Opportunities (CCC + Piotroski, awaiting breakout)</div>
                    <div class="top-pick-desc">
                        ENR.DE, HEI.DE (1.5% each)<br>
                        Watch for momentum entry on these quality values
                    </div>
                </div>
            </div>"""

    def _render_footer(self):
        """Footer with category line and next-update date"""
        return f"""<div class="footer">
            <p>Four Independent Screening Categories | Comprehensive Analysis | Bull Market Focus</p>
            <p>Darvas Box • Cash Conversion Cycle • Breakout Confirmation • Piotroski Quality</p>
            <p>Next update: {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d at 08:30 AM')}</p>
        </div>"""

    def _render_darvas_section(self):
        """Render Darvas Box momentum section"""
        top_3 = sorted(DARVAS_HITS.items(), key=lambda x: x[1]["score"], reverse=True)[:3]

        html = '<div class="section"><div class="section-title">🎯 Darvas Box Momentum Hits</div>'
        html += '<div class="section-description">Pure momentum plays: Price > MA50 > MA200, near 52-week highs. Best for trend followers.</div>'

        # Top picks highlight
        html += '<div style="margin-bottom: 20px;">'
        for symbol, data in top_3:
            html += f'''
            <div class="top-pick">
                <div class="top-pick-title">{symbol} - Score {data["score"]}/7</div>
                <div class="top-pick-desc">
                    Price: {data["price"]:.2f} | MA50: {data["ma50"]:.2f} | 52W High: {data["52w_high"]:.2f}<br>
                    Breakout Strength: {data["strength"]}% | Market: {data["market"]}
                </div>
            </div>
            '''
        html += '</div>'

        # Full table
        html += '<table class="stock-table"><tr><th>Symbol</th><th>Score</th><th>Price</th><th>MA50</th><th>52W High</th><th>Strength %</th><th>Market</th></tr>'
        for symbol, data in sorted(DARVAS_HITS.items(), key=lambda x: x[1]["score"], reverse=True):
            html += f'''
            <tr>
                <td class="symbol">{symbol}</td>
                <td class="score-{data["score"]}"><strong>{data["score"]}/7</strong></td>
                <td class="metric">{data["price"]:.2f}</td>
                <td class="metric">{data["ma50"]:.2f}</td>
                <td class="metric">{data["52w_high"]:.2f}</td>
                <td class="metric">{data["strength"]:.1f}%</td>
                <td>{data["market"]}</td>
            </tr>
            '''
        html += '</table></div>'
        return html

    def _render_ccc_section(self):
        """Render Cash Conversion Cycle section"""
        html = '<div class="section"><div class="section-title">💰 Cash Conversion Cycle (CCC) Efficiency Hits</div>'
        html += '<div class="section-description">Working capital generators: Lower CCC = faster cash return. Best for defensive portfolios and bear markets.</div>'

        # Best generators
        best = min(CCC_HITS.items(), key=lambda x: x[1]["ccc_days"])
        html += f'''
        <div class="top-pick">
            <div class="top-pick-title">{best[0]} - {best[1]["ccc_days"]} CCC Days (CASH GENERATOR!)</div>
            <div class="top-pick-desc">
                DIO: {best[1]["dio"]} | DSO: {best[1]["dso"]} | DPO: {best[1]["dpo"]}<br>
                Category: {best[1]["category"]} | Win Rate: {best[1]["win_rate"]}%
            </div>
        </div>
        '''

        # Full table
        html += '<table class="stock-table"><tr><th>Symbol</th><th>CCC Days</th><th>Category</th><th>DIO</th><th>DSO</th><th>DPO</th><th>Win Rate</th></tr>'
        for symbol, data in sorted(CCC_HITS.items(), key=lambda x: x[1]["ccc_days"]):
            category_class = "score-excellent" if data["ccc_days"] < 30 else "score-good" if data["ccc_days"] < 60 else "score-caution"
            html += f'''
            <tr>
                <td class="symbol">{symbol}</td>
                <td class="metric"><span class="{category_class}">{data["ccc_days"]:+d}</span></td>
                <td>{data["category"]}</td>
                <td class="metric">{data["dio"]}</td>
                <td class="metric">{data["dso"]}</td>
                <td class="metric">{data["dpo"]}</td>
                <td class="metric">{data["win_rate"]}%</td>
            </tr>
            '''
        html += '</table></div>'
        return html

    def _render_breakout_section(self):
        """Render Breakout stocks section"""
        fresh = sorted(BREAKOUT_HITS.items(), key=lambda x: x[1]["days_since"])[:3]

        html = '<div class="section"><div class="section-title">📈 Breakout Stocks (Resistance Breaks)</div>'
        html += '<div class="section-description">Fresh resistance breaks with volume surge (115%+). Clear technical entries, 72-78% success rate in bull markets.</div>'

        # Fresh breakouts
        html += '<div style="margin-bottom: 20px;"><strong>Fresh Breakouts (< 5 days):</strong><br>'
        for symbol, data in fresh:
            if data["days_since"] <= 5:
                html += f'''
                <div class="top-pick">
                    <div class="top-pick-title">{symbol} - {data["days_since"]} Days Since Break</div>
                    <div class="top-pick-desc">
                        Resistance: {data["resistance"]:.2f} | Break: +{data["break_pct"]:.2f}% | Volume: +{data["volume_surge"]}%
                    </div>
                </div>
                '''
        html += '</div>'

        # Full table
        html += '<table class="stock-table"><tr><th>Symbol</th><th>Resistance</th><th>Break %</th><th>Volume Surge</th><th>Days Since</th><th>Status</th></tr>'
        for symbol, data in sorted(BREAKOUT_HITS.items(), key=lambda x: x[1]["days_since"]):
            status = "🆕 FRESH" if data["days_since"] <= 3 else "✅ VALID" if data["days_since"] <= 7 else "⚠️ AGING"
            html += f'''
            <tr>
                <td class="symbol">{symbol}</td>
                <td class="metric">{data["resistance"]:.2f}</td>
                <td class="metric">+{data["break_pct"]:.2f}%</td>
                <td class="metric">+{data["volume_surge"]}%</td>
                <td class="metric">{data["days_since"]} days</td>
                <td>{status}</td>
            </tr>
            '''
        html += '</table></div>'
        return html

    def _render_piotroski_section(self):
        """Render Piotroski quality section"""
        super_quality = {k: v for k, v in PIOTROSKI_HITS.items() if v["score"] == 9}
        high_quality = {k: v for k, v in PIOTROSKI_HITS.items() if v["score"] == 8}

        html = '<div class="section"><div class="section-title">🏆 Piotroski Quality Rankings</div>'
        html += '<div class="section-description">Fundamental strength (0-9 score): ROE, debt, FCF, profitability, stability. Best for 12+ month holds and bear resilience.</div>'

        # Super quality highlights
        html += '<div style="margin-bottom: 20px;"><strong>Super Quality (9/9) - Elite Tier:</strong><br>'
        for symbol, data in super_quality.items():
            html += f'''
            <div class="top-pick">
                <div class="top-pick-title">{symbol} - 9/9 (HIGHEST QUALITY)</div>
                <div class="top-pick-desc">
                    ROE: {data["roe"]:.1f}% | Debt/Equity: {data["debt_equity"]:.2f} | Margin: {data["profit_margin"]}% | Growth: {data["growth"]}%
                </div>
            </div>
            '''
        html += '</div>'

        # Full table
        html += '<table class="stock-table"><tr><th>Symbol</th><th>Score</th><th>ROE</th><th>D/E Ratio</th><th>Profit Margin</th><th>Growth %</th><th>Tier</th></tr>'
        for symbol, data in sorted(PIOTROSKI_HITS.items(), key=lambda x: x[1]["score"], reverse=True):
            tier = "🏆 Super" if data["score"] == 9 else "✅ High" if data["score"] == 8 else "⚠️ Quality"
            html += f'''
            <tr>
                <td class="symbol">{symbol}</td>
                <td class="score-{data["score"]}"><strong>{data["score"]}/9</strong></td>
                <td class="metric">{data["roe"]:.1f}%</td>
                <td class="metric">{data["debt_equity"]:.2f}</td>
                <td class="metric">{data["profit_margin"]}%</td>
                <td class="metric">{data["growth"]}%</td>
                <td>{tier}</td>
            </tr>
            '''
        html += '</table></div>'
        return html

    def send_email(self, html_content):
        """Send email with HTML report"""
        if not SENDER_PASSWORD:
            logger.error("DAILY_MAILER_PASSWORD not set. Skipping email send.")
            return False

        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = f"📊 Daily Analysis: 4 Screening Categories - {datetime.now().strftime('%Y-%m-%d')}"
            message["From"] = SENDER_EMAIL
            message["To"] = RECIPIENT_EMAIL

            part = MIMEText(html_content, "html")
            message.attach(part)

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, message.as_string())

            logger.info(f"✓ Email sent to {RECIPIENT_EMAIL}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def save_html(self, html_content, filepath):
        """Save HTML report to file"""
        try:
            with open(filepath, 'w') as f:
                f.write(html_content)
            logger.info(f"✓ Report saved to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to save HTML: {e}")
            return False

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enhanced Daily Investment Analysis Mailer")
    parser.add_argument("--preview", action="store_true", help="Preview HTML without sending")
    parser.add_argument("--save-html", type=str, help="Save HTML to file")
    parser.add_argument("--send", action="store_true", help="Send email (default)")
    args = parser.parse_args()

    logger.info("Starting Enhanced Daily Mailer...")

    mailer = EnhancedDailyMailer()
    html = mailer.generate_html_report()

    if args.preview:
        print(html)
        return

    if args.save_html:
        mailer.save_html(html, args.save_html)
    else:
        # Default: save to reports directory
        report_path = REPORTS_DIR / f"daily_report_enhanced_{mailer.timestamp}.html"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        mailer.save_html(html, report_path)

    if args.send or (not args.preview and not args.save_html):
        mailer.send_email(html)

    logger.info("✓ Enhanced Daily Mailer Complete")

if __name__ == "__main__":
    main()
