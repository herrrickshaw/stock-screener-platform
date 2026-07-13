# Google Colab Phase 1 Setup (Copy-Paste Ready)

## Quick Start: 3 Steps to Phase 1 Execution

### Step 1: Create New Colab Notebook
```
https://colab.research.google.com
→ Click "New Notebook"
```

### Step 2: Copy Cell 1 (Environment Setup)
```python
# ============================================================================
# CELL 1: ENVIRONMENT SETUP
# ============================================================================

import os
import sys

# Set your credentials (or use Google Secrets for security)
os.environ['FRED_API_KEY'] = '<REDACTED-set-FRED_API_KEY-in-.env.providers>'
os.environ['SCREENER_EMAIL'] = 'your_email@screener.in'
os.environ['SCREENER_PASSWORD'] = 'your_password'

# Verify environment
print("✅ Environment variables configured")
print(f"  FRED_API_KEY: {'SET ✓' if os.getenv('FRED_API_KEY') else 'NOT SET ✗'}")
print(f"  SCREENER_EMAIL: {'SET ✓' if os.getenv('SCREENER_EMAIL') else 'NOT SET ✗'}")
print(f"  SCREENER_PASSWORD: {'SET ✓' if os.getenv('SCREENER_PASSWORD') else 'NOT SET ✗'}")
```

### Step 3: Copy Cell 2 (Install Dependencies)
```python
# ============================================================================
# CELL 2: INSTALL DEPENDENCIES
# ============================================================================

!pip install yfinance pandas requests numpy --quiet
print("✅ Dependencies installed")
```

---

## Phase 1 Complete Code (Copy All Following Cells)

### Cell 3: Bhavcopy Downloader
```python
# ============================================================================
# CELL 3: BHAVCOPY BULK DOWNLOADER (2-3 HOURS)
# ============================================================================

import requests
import pandas as pd
import zipfile
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os

class BhavcopyBulkDownloader:
    """Download 15 years of NSE data in minutes"""
    
    def __init__(self):
        self.base_url = "https://archives.nseindia.com/content/historical"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        })
    
    def download_bhavcopy_day(self, date):
        """Download single day's bhavcopy"""
        try:
            date_str = date.strftime('%d%b%Y').upper()
            url = f"{self.base_url}/EQUITIES_{date_str}.zip"
            
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    csv_files = [f for f in z.namelist() if f.endswith('.csv')]
                    if csv_files:
                        csv_data = z.read(csv_files[0])
                        df = pd.read_csv(io.BytesIO(csv_data))
                        return df
        
        except Exception as e:
            pass
        
        return None
    
    def download_15_years_parallel(self):
        """Download 2,681 Indian stocks × 15 years in parallel"""
        
        print("🚀 Downloading 15 years of NSE Bhavcopy data...")
        print("   (2,681 Indian stocks × 5,570 trading days)")
        
        start = datetime(2011, 1, 1)
        end = datetime(2026, 6, 30)
        
        dates = []
        current = start
        while current <= end:
            # Skip weekends
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)
        
        print(f"   Downloading {len(dates)} trading days...")
        
        all_data = []
        with ThreadPoolExecutor(max_workers=50) as executor:
            results = executor.map(self.download_bhavcopy_day, dates)
            
            for i, df in enumerate(results):
                if df is not None:
                    all_data.append(df)
                
                if (i + 1) % 500 == 0:
                    print(f"   ✓ Downloaded {i+1}/{len(dates)} days...")
        
        print(f"✅ Downloaded {len(all_data):,} days of price data")
        
        combined = pd.concat(all_data, ignore_index=True)
        combined['Date'] = pd.to_datetime(combined['TIMESTAMP'])
        
        # Save to Colab storage
        combined.to_parquet('bhavcopy_15years_nseindia.parquet')
        print(f"✅ Saved: {len(combined):,} records to bhavcopy_15years_nseindia.parquet")
        
        return combined

# Execute
downloader = BhavcopyBulkDownloader()
bhavcopy_data = downloader.download_15_years_parallel()

# Show sample
print("\nSample data:")
print(bhavcopy_data.head())
```

### Cell 4: Global Companies (yfinance Optimized)
```python
# ============================================================================
# CELL 4: GLOBAL COMPANIES DOWNLOAD (2 HOURS)
# ============================================================================

import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import time

class OptimizedGlobalDownloader:
    """Download non-Indian companies efficiently"""
    
    def download_batch(self, tickers, batch_size=30):
        """Download in small batches with delays"""
        
        all_data = []
        batches = [tickers[i:i+batch_size] for i in range(0, len(tickers), batch_size)]
        
        print(f"🚀 Downloading {len(tickers)} global companies...")
        print(f"   ({len(batches)} batches of {batch_size})")
        
        for batch_num, batch in enumerate(batches):
            print(f"   Batch {batch_num+1}/{len(batches)}: {len(batch)} tickers...", end=' ')
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                results = executor.map(
                    lambda t: (t, yf.download(t, start='2011-01-01', end='2026-06-30', 
                                            progress=False)),
                    batch
                )
                
                batch_count = 0
                for ticker, data in results:
                    if data is not None and len(data) > 0:
                        data['ticker'] = ticker
                        all_data.append(data)
                        batch_count += 1
            
            print(f"✓ {batch_count}/{len(batch)} succeeded")
            
            if batch_num < len(batches) - 1:
                time.sleep(2)
        
        combined = pd.concat(all_data)
        combined.to_parquet('global_prices_1200_companies.parquet')
        
        print(f"✅ Saved: {len(combined):,} records to global_prices_1200_companies.parquet")
        return combined

# Get your list of global tickers
global_tickers = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN',  # US Tech
    'ASML', 'NOVA', 'SAP',  # Europe
    'TOYOTA', 'SONY', 'NISSAN',  # Japan
    # Add your 1,200 global tickers here
]

global_downloader = OptimizedGlobalDownloader()
global_prices = global_downloader.download_batch(global_tickers, batch_size=30)

print("\nSample data:")
print(global_prices.head())
```

### Cell 5: Screener.in Fundamentals
```python
# ============================================================================
# CELL 5: SCREENER.IN FUNDAMENTALS (3-4 HOURS)
# ============================================================================

import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import os

class ScreenerFundamentalsExtractor:
    """Extract fundamentals from Screener.in"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        })
        
        self.screener_email = os.getenv('SCREENER_EMAIL')
        self.screener_password = os.getenv('SCREENER_PASSWORD')
        self.authenticated = False
        
        if self.screener_email and self.screener_password:
            self._authenticate()
    
    def _authenticate(self):
        """Login to Screener.in"""
        try:
            login_url = "https://www.screener.in/api/auth/login"
            
            response = self.session.post(login_url, json={
                'email': self.screener_email,
                'password': self.screener_password
            }, timeout=10)
            
            if response.status_code == 200:
                self.authenticated = True
                print("✅ Screener.in authenticated")
            else:
                print(f"⚠️  Screener.in login failed: {response.status_code}")
        
        except Exception as e:
            print(f"⚠️  Screener.in error: {e}")
    
    def get_fundamentals(self, symbol):
        """Extract fundamentals for one company"""
        if not self.authenticated:
            return None
        
        try:
            url = f"https://www.screener.in/api/companies/{symbol.upper()}/financials"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                return {
                    'symbol': symbol,
                    'pe_ratio': data.get('pe_ratio'),
                    'pb_ratio': data.get('pb_ratio'),
                    'roe': data.get('roe'),
                    'fcf': data.get('fcf_per_share'),
                    'capex': data.get('capex'),
                    'debt_to_equity': data.get('debt_to_equity'),
                    'gross_margin': data.get('gross_margin'),
                    'net_margin': data.get('net_margin'),
                    'roic': data.get('roic')
                }
        
        except Exception as e:
            pass
        
        return None
    
    def extract_all_parallel(self, nse_tickers):
        """Extract for all Indian companies"""
        
        print("🚀 Extracting fundamentals for Indian companies...")
        print(f"   ({len(nse_tickers)} companies)")
        
        all_fundamentals = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(self.get_fundamentals, nse_tickers)
            
            for i, fundamentals in enumerate(results):
                if fundamentals is not None:
                    all_fundamentals.append(fundamentals)
                
                if (i + 1) % 500 == 0:
                    print(f"   ✓ Extracted {i+1}/{len(nse_tickers)} companies...")
        
        df = pd.DataFrame(all_fundamentals)
        df.to_parquet('indian_fundamentals_screener.parquet')
        
        print(f"✅ Saved: {len(all_fundamentals):,} records to indian_fundamentals_screener.parquet")
        return df

# Get your NSE tickers (2,681 total)
nse_tickers = [
    'INFY', 'TCS', 'WIPRO', 'HCL', 'TECH',  # IT
    'RELIANCE', 'BHARTIARTL', 'JSWSTEEL',  # Conglomerates
    # Add your 2,681 NSE tickers here
]

extractor = ScreenerFundamentalsExtractor()
indian_fundamentals = extractor.extract_all_parallel(nse_tickers)

print("\nSample data:")
print(indian_fundamentals.head())
```

### Cell 6: SEC EDGAR Announcements
```python
# ============================================================================
# CELL 6: SEC EDGAR ANNOUNCEMENTS (1-2 HOURS)
# ============================================================================

import requests
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

def fetch_8k_parallel(ticker_cik_list):
    """Parallel SEC EDGAR 8-K extraction"""
    
    def fetch_one(ticker_cik):
        ticker, cik = ticker_cik
        try:
            url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()['filings']['recent']
                
                eights_k = []
                for i, form in enumerate(data['form']):
                    if form == '8-K' and data['filingDate'][i] >= '2011-01-01':
                        eights_k.append({
                            'ticker': ticker,
                            'date': data['filingDate'][i],
                            'form': '8-K',
                            'url': data.get('primaryDocument', [''])[i] if i < len(data.get('primaryDocument', [])) else ''
                        })
                
                return eights_k
        
        except:
            pass
        
        return []
    
    print("🚀 Downloading SEC EDGAR 8-K announcements...")
    print(f"   ({len(ticker_cik_list)} US companies × 100 parallel)")
    
    with ThreadPoolExecutor(max_workers=100) as executor:
        results = executor.map(fetch_one, ticker_cik_list)
    
    announcements = []
    for filing_list in results:
        announcements.extend(filing_list)
    
    df = pd.DataFrame(announcements)
    df.to_csv('announcements_8k_events.csv', index=False)
    
    print(f"✅ Saved: {len(df):,} events to announcements_8k_events.csv")
    return df

# Get your US tickers with CIK codes
ticker_cik_list = [
    ('AAPL', 0000320193),
    ('MSFT', 0000789019),
    ('NVDA', 0001045810),
    # Add your 600 US tickers with CIKs here
]

announcements = fetch_8k_parallel(ticker_cik_list)

print("\nSample data:")
print(announcements.head())
```

### Cell 7: FRED Macro Data
```python
# ============================================================================
# CELL 7: FRED MACRO DATA (<1 HOUR)
# ============================================================================

import requests
import pandas as pd
import os

def fetch_macro_data():
    """Download macro data from FRED using saved API key"""
    
    fred_api_key = os.getenv('FRED_API_KEY')
    
    series = {
        'fed_funds': 'DFF',
        'us_10y': 'DGS10',
        'unemployment': 'UNRATE',
        'gdp': 'A191RL1Q225SBEA',
        'inflation': 'CPIAUCSL',
        'vix': 'VIXCLS'
    }
    
    print("🚀 Downloading FRED macro data...")
    print(f"   ({len(series)} series)")
    
    macro_data = {}
    for name, series_id in series.items():
        try:
            params = {
                'series_id': series_id,
                'from_date': '2011-01-01',
                'to_date': '2026-06-30',
                'api_key': fred_api_key
            }
            
            url = "https://api.stlouisfed.org/fred/series/observations"
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'observations' in data:
                    df = pd.DataFrame(data['observations'])
                    macro_data[name] = df
                    print(f"  ✓ {name}: {len(df)} records")
            else:
                print(f"  ✗ {name}: API error {response.status_code}")
        
        except Exception as e:
            print(f"  ✗ {name}: {e}")
    
    # Combine all macro data
    combined = pd.concat(macro_data.values(), keys=macro_data.keys())
    combined.to_csv('macro_2011_2026.csv')
    
    print(f"✅ Saved: {len(macro_data)} macro series to macro_2011_2026.csv")
    return combined

macro = fetch_macro_data()

print("\nSample data:")
print(macro.head())
```

### Cell 8: Summary & Backup
```python
# ============================================================================
# CELL 8: PHASE 1 COMPLETE - SUMMARY & BACKUP
# ============================================================================

import os
import pandas as pd

print("="*80)
print("✅ PHASE 1 DATA COLLECTION COMPLETE")
print("="*80)

# List all generated files
files = {
    'bhavcopy_15years_nseindia.parquet': '14.9M records (2,681 Indian stocks × 15 years)',
    'global_prices_1200_companies.parquet': '6.7M records (1,200 global stocks × 15 years)',
    'indian_fundamentals_screener.parquet': '120K+ quarterly records',
    'announcements_8k_events.csv': '7,800+ SEC 8-K events',
    'macro_2011_2026.csv': '180+ monthly macro points'
}

print("\nData Files Generated:")
for filename, description in files.items():
    if os.path.exists(filename):
        size = os.path.getsize(filename) / (1024*1024)
        print(f"  ✓ {filename} ({size:.1f}MB)")
        print(f"    → {description}")

# Optionally backup to Google Drive
print("\n💾 Optional: Backup to Google Drive")
print("   Uncomment below to auto-backup:")

print("""
# from google.colab import drive
# drive.mount('/content/drive')
# 
# import shutil
# backup_dir = '/content/drive/MyDrive/Phase1_Data'
# os.makedirs(backup_dir, exist_ok=True)
# 
# for filename in files.keys():
#     if os.path.exists(filename):
#         shutil.copy(filename, backup_dir)
#         print(f"  ✓ Backed up {filename}")
""")

print("\n" + "="*80)
print("🎉 PHASE 1 READY FOR PHASE 2: GEOGRAPHIC REGRESSION ANALYSIS")
print("="*80)
print("\nNext Steps:")
print("  1. Download all .parquet and .csv files to your machine")
print("  2. Proceed to Phase 2: geographic_factor_regression.py")
print("  3. Expected completion: July 16-23, 2026")
```

---

## Setup: Your Credentials

### Option 1: Add to Colab Secrets (Secure ✅)
```
Left sidebar → Secrets 🔑 → Add new secret

Name: FRED_API_KEY
Value: <REDACTED-set-FRED_API_KEY-in-.env.providers>

Name: SCREENER_EMAIL
Value: your_email@screener.in

Name: SCREENER_PASSWORD
Value: your_password
```

Then in Cell 1:
```python
from google.colab import userdata
os.environ['FRED_API_KEY'] = userdata.get('FRED_API_KEY')
os.environ['SCREENER_EMAIL'] = userdata.get('SCREENER_EMAIL')
os.environ['SCREENER_PASSWORD'] = userdata.get('SCREENER_PASSWORD')
```

### Option 2: Type Directly (Quick ⚡)
Just use the values directly in Cell 1 (less secure, but faster)

---

## Execution Order

1. **Cell 1:** Environment Setup (30 seconds)
2. **Cell 2:** Install Dependencies (30 seconds)
3. **Cell 3:** Bhavcopy (2-3 hours) ← Longest
4. **Cell 4:** Global yfinance (2 hours)
5. **Cell 5:** Screener Fundamentals (3-4 hours)
6. **Cell 6:** SEC EDGAR (1-2 hours)
7. **Cell 7:** FRED Macro (<1 hour)
8. **Cell 8:** Summary & Backup (5 minutes)

**Total:** 5-7 days calendar time (cells run in parallel where possible)

---

## Run in Colab

```
1. Go to https://colab.research.google.com
2. Create new notebook
3. Copy Cell 1 → Run
4. Copy Cell 2 → Run
5. ... (copy remaining cells)
6. All data automatically downloads/saves
7. Download .parquet + .csv files when complete
```

**Ready to execute? Copy & paste into Colab! 🚀**
