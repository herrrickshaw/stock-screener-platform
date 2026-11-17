# Multi-market stock screener platform

A research and education toolkit for screening listed equities in India (NSE/BSE), the US, Europe, Japan and Korea.
It combines a FastAPI + React app (live screening, portfolio P&L, an all-market daily scan backed by Cassandra),
standalone Python/R screening pipelines (Pegu score, Sarvas scan), and a put-call-parity research module.
Outputs are CSV reports, JSON API responses, a dashboard and an HTML daily mailer.

> Status: maintained, research-only. Educational use only; not investment advice. See the reconciliation
> caution below before trusting any return figure this repo has previously quoted.

> **Reconciled 2026-07-14.** Earlier versions of this README claimed "production-ready" status and a 22.4% blended
> annual return. Those figures trace to a 272-stock sample and were never confirmed by the rigorous point-in-time
> backtest (SEC EDGAR + yfinance, fold-cross-validated), which reaches the opposite conclusion for the US and finds
> quality signals useful only as a breakout-confirmation overlay elsewhere. See
> [`STOCK_ANALYSIS_MASTER_SUMMARY.md` in herrrickshaw/BMS_analysis_battery](https://github.com/herrrickshaw/BMS_analysis_battery/blob/main/STOCK_ANALYSIS_MASTER_SUMMARY.md).
> The win-rate and return tables were removed here for that reason.

## What it does
- Scores instruments with a vectorised Darvas/Buffett scan (0-13 criteria) and a simplified Piotroski scan (0-11) over OHLCV + RSI quotes (`backend/scanners/daily_scanner.py`).
- Runs the full Screener.in-CSV scanners: Darvas+Buffett, 9-point Piotroski and Coffee Can (`backend/scanners/`).
- Serves a REST API for live yfinance fetches, CSV uploads, Excel/PDF portfolio parsing with P&L, dividends and RSI signals (`backend/routers/`).
- Seeds and bulk-fetches quotes for ~20k instruments into a local Cassandra keyspace `herrrickshaw` (`backend/db/`).
- Scores NSE/BSE fundamentals with the R pipeline (`pegu_sarvas_analysis.R`, `run_pegu_sarvas.sh`).
- Detects put-call-parity mispricings net of STT, exchange, brokerage, GST and SEBI costs (`put_call_parity/`, research code; broker credentials are never committed).

## Quick start
```bash
git clone https://github.com/herrrickshaw/stock-screener-platform.git
cd stock-screener-platform
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run_app.sh            # backend :8000 + frontend :5173
```
`run_app.sh` refreshes the instrument lists on every start (NSE `EQUITY_L.csv`, NASDAQ trader files, JPX, FinanceDataReader
for Korea, Wikipedia index scrapes for Europe, akshare for China) and runs the backend with `--reload`.
The Pegu/Sarvas R pipeline: `./run_pegu_sarvas.sh [nifty50 | all]` (default NIFTY500 + BSE).

## How it works
| Stage | Module | Output |
|---|---|---|
| Instrument lists | `run_app.sh`, `backend/db/seeder.py` | Cassandra `instruments*` tables |
| Quote fetch (Phase 1: OHLCV, RSI-14, EMA-50, batches of 50) | `backend/db/bulk_fetcher.py` | `stock_quotes`, `price_history` |
| Fundamentals (Phase 2, optional, 1-3 h) | `backend/db/bulk_fetcher.py` | PE, PB, ROE, OPM, D/E, market cap |
| Daily scan | `backend/scanners/daily_scanner.py` via `POST /api/db/daily/scan` | BUY / WATCH / AVOID per market |
| Full scans on uploaded CSV | `backend/scanners/{darvas,piotroski,coffee_can}.py` | scored rows + criteria |
| Portfolio P&L | `backend/parsers/`, `backend/fetchers/history.py` | holdings with returns, dividends, RSI |
| Reports | `daily_mailer*.py`, `morning_ocaml_routine.sh` | HTML report / email (scheduled by the owner) |

Design decisions that matter:
- **Cassandra ticker format.** India is stored as bare NSE symbols (`HDFCBANK`); every other market stores the pre-suffixed yfinance ticker (`7203.T`, `ADS.DE`).
  `backend/fetchers/tickers.py` (`bare_ticker`, `market_from_ticker`) is the single place that maps suffixes to market partitions; an unqualified symbol falls into `us`, so always pass exchange-qualified tickers.
- **Daily scanner vs full scanners.** `daily_scanner.py` needs only Phase-1 data; the Piotroski BUY/WATCH thresholds are `ceil(max*0.65)` / `ceil(max*0.40)` of the criteria actually available, so sparse data still yields signals. The full scanners need Screener.in exports.
- **Darvas.** BUY >= 5, WATCH >= 3 on the 0-13 daily scale; the daily scanner uses 52-week-high proximity, not a rolling box.
- **R for scoring.** The Pegu/Sarvas pipeline deliberately stays in R.

## Repository layout
| Path | Purpose |
|---|---|
| `backend/` | FastAPI app: `routers/`, `scanners/`, `fetchers/`, `parsers/`, `db/` (Cassandra), `events/`, `scheduler.py` |
| `frontend/` | React + Vite + Tailwind UI (Daily Report, Screener Scan, Live Scan, Compare, Sector Benchmarks, Portfolio upload) |
| `put_call_parity/` | Parity engine, strategy loop, broker adapters, position book |
| `tests/` | pytest suite on synthetic frames (golden snapshots from pre-refactor code); no network, no database |
| `data/` | Reference lists (Europe/Frankfurt/London, NSE/BSE fundamentals, Damodaran) and samples |
| `reports/` | Benchmark output; generated reports are not hand-edited |
| `docs/` | GitHub Pages site and generators |
| `Downloads/`, `global_expansion_screener_framework/`, `api-data-integration/` | Legacy snapshots and experiments (not refactored; see Phase 2) |
| `CLAUDE.md` | Contributor/agent guide (commands, endpoints, hazards) |

## Data sources
| Source | What is taken | Access route | Licence / caveat |
|---|---|---|---|
| yfinance (Yahoo Finance) | OHLCV, fundamentals, dividends | `yfinance` library | Unofficial; terms of Yahoo apply; `auto_adjust` can miss recent JP/KR splits |
| NSE `EQUITY_L.csv`, NASDAQ trader files, JPX `data_j.xls` | Instrument lists | HTTP download in `run_app.sh` | Public listings; refreshed daily, not committed |
| FinanceDataReader, akshare | Korea / China lists | Python libraries | Third-party scrapers |
| Wikipedia index pages | Europe constituents | Scraped | Rebuilt if older than 30 days |
| Screener.in CSV export | Fundamentals for the full scanners | User upload | User's own export; do not redistribute |
| Damodaran sector data | PE/PB benchmarks | `data/damodaran` | Academic dataset |

## Configuration
- Cassandra on localhost, keyspace `herrrickshaw` (see `backend/db/cassandra_client.py`).
- Optional data-provider keys are read from environment variables (`backend/config/providers.py`); keep them in a git-ignored `.env.providers`.
- Broker credentials for `put_call_parity/config.py` are local only and must never be committed.

## Testing
```bash
pip install pytest pandas numpy
pytest -q          # 36 tests: scanner golden snapshots, ticker routing, parity maths
```
CI (`.github/workflows/ci.yml`) runs ruff on the refactored modules, `compileall` and pytest.

## Limitations and known issues
- Performance claims from earlier README versions are retracted (see the reconciliation note above).
- Only a few modules have tests; routers, Cassandra access, parsers and the legacy scripts are untested.
- Phase-1 scans have no fundamentals unless Phase 2 has run, so Buffett/Piotroski quality criteria are often absent (`completeness` shows how many were evaluable).
- Several top-level docs referenced by older READMEs (`QUICK_START.md`, `INTEGRATED_SYSTEM_SUMMARY.md`, `MAILER_INTEGRATION_GUIDE.md`, `SETUP_AND_REQUIREMENTS.md`) do not exist.
- The daily mailer's `--send` path has no already-sent guard.
- Some large tracked databases under `global_expansion_screener_framework/` are Git LFS pointers; see `DATA_ACCESS.md`.

## Related repositories
- [herrrickshaw/BMS_analysis_battery](https://github.com/herrrickshaw/BMS_analysis_battery): point-in-time backtests that supersede this repo's earlier return claims.

## Licence
No licence file yet; all rights reserved.
