# 🌍 Global Stock Screening System
**Production-ready multi-market stock analysis with OCaml, universal screens & validation**

> **⚠️ RECONCILED 2026-07-14 — the "production-ready" and return claims in this README are not validated.**
> The 22.4% blended-return figure and the underlying "Piotroski quality dominates all markets" premise trace back to a 272-stock sample, never confirmed against the account's actual rigorous point-in-time backtest (SEC EDGAR + yfinance, fold-cross-validated) — which reaches the opposite conclusion for the US and shows quality signals work only as a breakout-confirmation overlay elsewhere. See [`STOCK_ANALYSIS_MASTER_SUMMARY.md` in herrrickshaw/BMS_analysis_battery](https://github.com/herrrickshaw/BMS_analysis_battery/blob/main/STOCK_ANALYSIS_MASTER_SUMMARY.md) for the reconciled, source-linked recommendations before trusting this system's output. (This README also references several docs — `QUICK_START.md`, `INTEGRATED_SYSTEM_SUMMARY.md`, `MAILER_INTEGRATION_GUIDE.md`, `DEPLOYMENT_CHECKLIST.md`, `SETUP_AND_REQUIREMENTS.md` — that don't exist in this repo; those links are stale and unrelated to this banner.)

---

## 🎯 What This Is

A **complete, automated stock screening system** that runs every morning at 08:00 AM and:

- ✅ Analyzes **20,434 stocks** across 5 markets (India, US, Europe, Japan, Korea)
- ✅ Generates **20-30 daily picks** with confidence scoring
- ✅ Runs **6 screens simultaneously** (OCaml + 5 fundamental)
- ✅ Detects **multi-screen confirms** (80%+ agreement = strongest signals)
- ✅ Validates **weekly win rates** with quarterly recalibration
- ✅ Produces **professional 8-section email** with comparison analytics
- ✅ Expected **22.4% annual return** (blended strategy)

---

## 📊 Performance Overview

| Screen | Market | Win Rate | Expected Return | Status |
|--------|--------|----------|-----------------|--------|
| **India Optimized** | India | 62.5% ⭐ | +4.2%/month | **BEST** |
| **CCC Legacy** | All | 60.0% | +3.9%/month | STRONG |
| **USA Optimized** | USA | 58.3% | +3.1%/month | STRONG |
| **Piotroski** | All | 54.5% | +3.4%/month | SOLID |
| **Darvas** | All | 50.0% | +2.8%/month | BASELINE |
| **Blended (all)** | Global | 22.4% | Annually | **BEST-IN-CLASS** |

---

## 📁 Documentation Index

### 🚀 Quick Start (Start Here!)
- **QUICK_START.md** — Deploy in 5 minutes
- **README.md** — This file, complete overview

### 📋 Setup & Installation
- **requirements.txt** — All Python dependencies
- **SETUP_AND_REQUIREMENTS.md** — Install on macOS/Linux/Windows/Docker
- **COLAB_QUICK_CHECK.ipynb** — Verify in Google Colab (5-10 min)

### 🔧 Deployment & Operations
- **MORNING_ROUTINE_SETUP.md** — Daily automation guide
- **DEPLOYMENT_CHECKLIST.md** — Step-by-step deployment verification
- **morning_ocaml_routine.sh** — Main automated script

### 📚 System & Analysis
- **INTEGRATED_SYSTEM_SUMMARY.md** — System architecture
- **MAILER_INTEGRATION_GUIDE.md** — Email integration
- **FILTER_MARKET_INSIGHTS_ANALYSIS.md** — Market analysis

---

## 🚀 Getting Started (5 Minutes)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Verify System Works
Open COLAB_QUICK_CHECK.ipynb in Google Colab (no local setup needed)

### Step 3: Deploy Locally
```bash
chmod +x morning_ocaml_routine.sh
mkdir -p logs reports
crontab -e
# Add: 0 8 * * 1-5 /Users/umashankar/morning_ocaml_routine.sh >> /Users/umashankar/logs/cron.log 2>&1
```

### Step 4: Run Manually (to test)
```bash
./morning_ocaml_routine.sh
open DAILY_SCREENING_REPORT.html
```

---

## ✅ Verification Checklist

- [ ] Install requirements.txt
- [ ] Run COLAB_QUICK_CHECK.ipynb in Google Colab
- [ ] Verify all imports work
- [ ] Make script executable
- [ ] Create log/report directories
- [ ] Add to crontab
- [ ] Test manual run
- [ ] Check output files

---

## 🎉 Status

🔴 **SUPERSEDED (2026-07-14)** — see reconciliation banner at top of this file; original claim was ✅ PRODUCTION READY

- All components built and tested
- Complete documentation provided
- Requirements file with all dependencies
- Google Colab verification notebook
- Ready for immediate deployment

**Next step: Read QUICK_START.md**

