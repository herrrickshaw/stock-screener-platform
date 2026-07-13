#!/usr/bin/env python3
"""
Comprehensive Data Source Validation
Tests: Bhavcopy, yfinance, repo cache, Screener.in, SEC EDGAR, FRED
"""

import os
import requests
import pandas as pd
import yfinance as yf
import zipfile
import io
from datetime import datetime, timedelta
import os
from concurrent.futures import ThreadPoolExecutor

print("="*80)
print("DATA COMPLETENESS TEST - All Sources")
print("="*80)
print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# ============================================================================
# 1. TEST BHAVCOPY (NSE Historical Archives)
# ============================================================================

print("1️⃣  BHAVCOPY (NSE Historical Archives)")
print("-" * 80)

def test_bhavcopy_date(date_str, date_obj):
    """Test if bhavcopy file exists for specific date"""
    try:
        url = f"https://archives.nseindia.com/content/historical/EQUITIES_{date_str}.zip"
        response = requests.head(url, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            return True, "✅"
        elif response.status_code == 404:
            return False, "❌ (404 Not Found)"
        else:
            return False, f"❌ ({response.status_code})"
    except Exception as e:
        return False, f"❌ ({str(e)[:30]})"

print("Testing Bhavcopy availability for sample dates:")
print("(Checking if archives exist for different years)\n")

test_dates = [
    (datetime(2011, 1, 3), "2011 (oldest)"),   # 2011-01-03 first trading day
    (datetime(2015, 6, 15), "2015 (mid)"),     # mid-range
    (datetime(2020, 1, 15), "2020 (recent)"),  # recent
    (datetime(2026, 6, 25), "2026 (latest)"),  # latest
]

bhavcopy_results = {}
for date_obj, label in test_dates:
    date_str = date_obj.strftime('%d%b%Y').upper()
    accessible, status = test_bhavcopy_date(date_str, date_obj)
    bhavcopy_results[label] = accessible
    print(f"  {status} {date_str} ({label})")

# Try to download sample data
print("\nTesting Bhavcopy actual download (2026-06-25):")
try:
    url = "https://archives.nseindia.com/content/historical/EQUITIES_25JUN2026.zip"
    response = requests.get(url, timeout=10)

    if response.status_code == 200:
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_files = [f for f in z.namelist() if f.endswith('.csv')]
            if csv_files:
                df = pd.read_csv(io.BytesIO(z.read(csv_files[0])))
                print(f"  ✅ Downloaded {len(df):,} records from {csv_files[0]}")
                print(f"     Columns: {list(df.columns)[:5]}")
                if 'TIMESTAMP' in df.columns:
                    dates = pd.to_datetime(df['TIMESTAMP']).dt.date
                    print(f"     Date range: {dates.min()} to {dates.max()}")
except Exception as e:
    print(f"  ❌ Download failed: {e}")

bhavcopy_status = "✅ AVAILABLE" if all(bhavcopy_results.values()) else "⚠️  PARTIAL"
print(f"\n→ Bhavcopy Status: {bhavcopy_status}")

# ============================================================================
# 2. TEST YFINANCE (Historical Data)
# ============================================================================

print("\n2️⃣  YFINANCE (Global Stock Data)")
print("-" * 80)

print("Testing yfinance for historical data (2011-2026):\n")

test_tickers = [
    ('AAPL', 'US Tech'),
    ('0001.HK', 'Hong Kong'),
    ('6758.T', 'Japan'),
    ('INFY.NS', 'India'),
]

yfinance_results = {}
for ticker, region in test_tickers:
    print(f"  Testing {ticker} ({region})...", end=' ')
    try:
        # Try to download 15 years of data
        df = yf.download(ticker, start='2011-01-01', end='2026-06-30', progress=False)

        if len(df) > 0:
            date_range = f"{df.index.min().date()} to {df.index.max().date()}"
            years = (df.index.max() - df.index.min()).days / 365.25
            records = len(df)
            print(f"✅ {records:,} records ({years:.1f} years)")
            print(f"     → {date_range}")
            yfinance_results[ticker] = True
        else:
            print(f"❌ No data")
            yfinance_results[ticker] = False
    except Exception as e:
        print(f"❌ Error: {str(e)[:40]}")
        yfinance_results[ticker] = False

yfinance_status = "✅ AVAILABLE" if all(yfinance_results.values()) else "⚠️  PARTIAL"
print(f"\n→ yfinance Status: {yfinance_status}")

# ============================================================================
# 3. TEST REPO CACHED DATA (LFS Files)
# ============================================================================

print("\n3️⃣  REPO CACHED DATA (LFS)")
print("-" * 80)

print("Testing existing parquet files in repo:\n")

cache_files = {
    'Downloads/code/python_files/cache_seed/cleaned_long_US.parquet': 'Global (US)',
    'Downloads/code/python_files/cache_seed/cleaned_long_JP.parquet': 'Global (JP)',
    'Downloads/code/python_files/cache_seed/cleaned_long_CN.parquet': 'Global (CN)',
    'nse_screener_reference/symbol_master.parquet': 'NSE Symbol Master',
}

repo_cache_results = {}
for file_path, label in cache_files.items():
    print(f"  {label}: ", end='')

    if os.path.exists(file_path):
        try:
            df = pd.read_parquet(file_path)
            print(f"✅ {len(df):,} records")

            # Check date range if available
            if 'Date' in df.columns:
                date_range = f"{df['Date'].min().date()} to {df['Date'].max().date()}"
                print(f"     → {date_range}")
            elif label == 'NSE Symbol Master':
                print(f"     → Columns: {list(df.columns)[:5]}")

            repo_cache_results[label] = True
        except Exception as e:
            print(f"❌ Error reading: {str(e)[:40]}")
            repo_cache_results[label] = False
    else:
        print(f"❌ File not found")
        repo_cache_results[label] = False

# Check OHLC cache
print(f"\n  OHLC Cache (Indian stocks): ", end='')
ohlc_cache_dir = 'nse_screener_reference/ohlc_cache'
if os.path.exists(ohlc_cache_dir):
    files = os.listdir(ohlc_cache_dir)
    if files:
        sample_file = f"{ohlc_cache_dir}/{files[0]}"
        try:
            df = pd.read_parquet(sample_file)
            print(f"✅ {len(files)} stocks cached")
            print(f"     → Sample: {files[0]} ({len(df):,} records)")
            print(f"     → Date range: {df.index.min().date()} to {df.index.max().date()}")
            repo_cache_results['OHLC Cache'] = True
        except Exception as e:
            print(f"⚠️  Error: {e}")
            repo_cache_results['OHLC Cache'] = False
    else:
        print(f"⚠️  Directory empty")
        repo_cache_results['OHLC Cache'] = False
else:
    print(f"❌ Directory not found")
    repo_cache_results['OHLC Cache'] = False

repo_status = "✅ AVAILABLE" if all(repo_cache_results.values()) else "⚠️  PARTIAL"
print(f"\n→ Repo Cache Status: {repo_status}")

# ============================================================================
# 4. TEST SCREENER.IN (Indian Fundamentals)
# ============================================================================

print("\n4️⃣  SCREENER.IN (Indian Fundamentals)")
print("-" * 80)

print("Testing Screener.in API connectivity:\n")

screener_email = 'umashankartd1991@gmail.com'
screener_password = 'REDACTED_PASSWORD'

try:
    session = requests.Session()
    response = session.post(
        'https://www.screener.in/api/auth/login',
        json={'email': screener_email, 'password': screener_password},
        timeout=10
    )

    if response.status_code == 200:
        print("  ✅ Authentication successful")

        # Try to fetch fundamentals for a stock
        resp = session.get('https://www.screener.in/api/companies/INFY/financials', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ Data fetch successful (INFY)")
            print(f"     → Available fields: {len(data)} keys")
            screener_status = "✅ AVAILABLE"
        else:
            print(f"  ⚠️  Data fetch failed ({resp.status_code})")
            screener_status = "⚠️  PARTIAL"
    else:
        print(f"  ❌ Authentication failed ({response.status_code})")
        screener_status = "❌ UNAVAILABLE"
except Exception as e:
    print(f"  ❌ Connection error: {str(e)[:50]}")
    screener_status = "❌ UNAVAILABLE"

print(f"\n→ Screener.in Status: {screener_status}")

# ============================================================================
# 5. TEST SEC EDGAR (US Announcements)
# ============================================================================

print("\n5️⃣  SEC EDGAR (US Announcements)")
print("-" * 80)

print("Testing SEC EDGAR API:\n")

try:
    # Test with Apple CIK
    response = requests.get(
        'https://data.sec.gov/submissions/CIK0000320193.json',
        timeout=10
    )

    if response.status_code == 200:
        data = response.json()
        filings = data['filings']['recent']

        # Count 8-K filings
        form_types = filings['form']
        eightk_count = sum(1 for f in form_types if f == '8-K')

        # Get date range
        dates = pd.to_datetime(filings['filingDate'])
        print(f"  ✅ API accessible")
        print(f"     → AAPL filings: {len(form_types)} total, {eightk_count} 8-K")
        print(f"     → Date range: {dates.min().date()} to {dates.max().date()}")
        sec_status = "✅ AVAILABLE"
    else:
        print(f"  ❌ API error ({response.status_code})")
        sec_status = "❌ UNAVAILABLE"
except Exception as e:
    print(f"  ❌ Connection error: {str(e)[:50]}")
    sec_status = "❌ UNAVAILABLE"

print(f"\n→ SEC EDGAR Status: {sec_status}")

# ============================================================================
# 6. TEST FRED (Macro Data)
# ============================================================================

print("\n6️⃣  FRED (Macro Data)")
print("-" * 80)

print("Testing FRED API (Federal Reserve data):\n")

fred_api_key = os.getenv('FRED_API_KEY')
if not fred_api_key:
    raise SystemExit("Set FRED_API_KEY in .env.providers before running this test.")

try:
    series_list = ['DFF', 'UNRATE', 'CPIAUCSL']  # Fed Funds, Unemployment, CPI
    fred_status_dict = {}

    for series_id in series_list:
        response = requests.get(
            'https://api.stlouisfed.org/fred/series/observations',
            params={
                'series_id': series_id,
                'from_date': '2011-01-01',
                'to_date': '2026-06-30',
                'api_key': fred_api_key
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if 'observations' in data:
                obs = data['observations']
                dates = pd.to_datetime([o['date'] for o in obs])
                print(f"  ✅ {series_id}: {len(obs)} observations")
                print(f"     → {dates.min().date()} to {dates.max().date()}")
                fred_status_dict[series_id] = True
            else:
                print(f"  ⚠️  {series_id}: No data")
                fred_status_dict[series_id] = False
        else:
            print(f"  ❌ {series_id}: Error {response.status_code}")
            fred_status_dict[series_id] = False

    fred_status = "✅ AVAILABLE" if all(fred_status_dict.values()) else "⚠️  PARTIAL"
except Exception as e:
    print(f"  ❌ Connection error: {str(e)[:50]}")
    fred_status = "❌ UNAVAILABLE"

print(f"\n→ FRED Status: {fred_status}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "="*80)
print("SUMMARY - Data Source Completeness")
print("="*80)

summary = {
    "Bhavcopy (2011+)": bhavcopy_status,
    "yfinance (2011+)": yfinance_status,
    "Repo Cache (LFS)": repo_status,
    "Screener.in": screener_status,
    "SEC EDGAR": sec_status,
    "FRED": fred_status,
}

for source, status in summary.items():
    print(f"  {source:.<40} {status}")

print("\n" + "="*80)

# Overall recommendation
all_available = all("✅" in s for s in summary.values())

if all_available:
    print("✅ VERDICT: All data sources available for 15-year historical analysis!")
    print("\nRecommendation:")
    print("  1. Use Bhavcopy for NSE Indian data (fastest, most reliable)")
    print("  2. Use yfinance for global data (reliable, 2011+ coverage)")
    print("  3. Use repo cache to skip redundant downloads (3-4x faster)")
    print("  4. Use Screener.in + SEC EDGAR + FRED for fundamentals & macro")
    print("\n→ Phase 1 can proceed with confidence! 🚀")
else:
    partial = sum(1 for s in summary.values() if "⚠️" in s)
    print(f"⚠️  VERDICT: {partial} sources partially available")
    print("\nRecommendation:")
    print("  1. Use available sources immediately")
    print("  2. Monitor unavailable sources (may be temporary)")
    print("  3. Have fallback sources ready if needed")
    print("\n→ Phase 1 can proceed with fallbacks in place")

print("\n" + "="*80)
print(f"Test completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)
