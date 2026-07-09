import boto3, io, os, pandas as pd, numpy as np, pyarrow.parquet as pq
import yfinance as yf, warnings
warnings.filterwarnings('ignore')

from dotenv import load_dotenv
load_dotenv()
s3 = boto3.client('s3', region_name='us-east-2')
B = 'options-data-lake-639098881709-us-east-2-an'

TICKERS = ['AAPL','NVDA','TSLA','AMD','MSFT','AMZN','META','GOOGL','NFLX','COIN','PLTR',
'BABA','DIS','JPM','BAC','C','WFC','GS','MS','V','MA','JNJ','UNH','LLY','MRK','ABBV',
'XOM','CVX','WMT','TGT','COST','HD','LOW','MCD','SBUX','NKE','KO','PEP','PG','GM',
'UBER','ABNB','DAL','UAL','RCL','ROKU','PYPL','HOOD','SNOW','CRWD','PANW','DDOG',
'ENPH','MSTR','MU','INTC','TSM','QCOM','AVGO','TXN','CRM','ADBE','NOW','UPST','AFRM','BA']

print(f"Step 1: Loading enriched chain for {len(TICKERS)} tickers...")
resp = s3.get_object(Bucket=B, Key='dashboard_data/enriched_chain_gold.parquet')
table = pq.read_table(io.BytesIO(resp['Body'].read()))
df = table.to_pandas()
df['date'] = pd.to_datetime(df['timestamp']).dt.date
df['date'] = pd.to_datetime(df['date'])
df = df[df['ticker'].isin(TICKERS)]
print(f"Filtered to {len(df):,} rows, {df['ticker'].nunique()} tickers, {df['date'].nunique()} dates")

# Clean
df['iv'] = pd.to_numeric(df['iv'], errors='coerce')
df['delta'] = pd.to_numeric(df['delta'], errors='coerce')
df['gamma'] = pd.to_numeric(df['gamma'], errors='coerce')
df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
df['open_interest'] = pd.to_numeric(df['open_interest'], errors='coerce').fillna(0)
df['strike'] = pd.to_numeric(df['strike'], errors='coerce')
df['underlying_price'] = pd.to_numeric(df['underlying_price'], errors='coerce')
df['exp_dt'] = pd.to_datetime(df['expiration'])
df['dte'] = (df['exp_dt'] - df['date']).dt.days
df = df[df['underlying_price'] > 0]

print("\nStep 2: Computing daily features per ticker...")
results = []

for ticker in TICKERS:
    td = df[df['ticker'] == ticker].sort_values('date')
    if td.empty:
        continue
    
    dates = sorted(td['date'].unique())
    
    for d in dates:
        day = td[td['date'] == d]
        if day.empty:
            continue
        
        spot = day['underlying_price'].iloc[0]
        
        # ---- VWKS (7-45 DTE calls) ----
        calls_fm = day[(day['side'] == 'CALL') & (day['dte'].between(7, 45))]
        if calls_fm.empty or calls_fm['volume'].sum() == 0:
            vwks = np.nan
        else:
            vwks = (calls_fm['strike'] * calls_fm['volume']).sum() / calls_fm['volume'].sum()
        
        # ---- Skew (7-60 DTE, 25Δ call - 25Δ put) ----
        skew_scope = day[(day['dte'].between(7, 60)) & (day['iv'] > 0) & (day['iv'] < 2.0)]
        c25 = skew_scope[(skew_scope['side'] == 'CALL') & (skew_scope['delta'].between(0.20, 0.30))]['iv'].mean()
        p25 = skew_scope[(skew_scope['side'] == 'PUT') & (skew_scope['delta'].between(-0.30, -0.20))]['iv'].mean()
        skew = (c25 - p25) if pd.notna(c25) and pd.notna(p25) else np.nan
        
        # ---- Term Structure (front 7-45 vs back 45+ ATM call IV) ----
        atm_c = day[(day['side'] == 'CALL') & (day['iv'] > 0) & (day['iv'] < 2.0)]
        atm_c['strike_dist'] = (atm_c['strike'] - spot).abs()
        
        fm_atm = atm_c[atm_c['dte'].between(7, 45)]
        bm_atm = atm_c[atm_c['dte'] > 45]
        
        iv_fm = np.nan
        iv_bm = np.nan
        if not fm_atm.empty:
            idx = fm_atm.groupby('expiration')['strike_dist'].idxmin()
            iv_fm = fm_atm.loc[idx]['iv'].mean()
        if not bm_atm.empty:
            idx = bm_atm.groupby('expiration')['strike_dist'].idxmin()
            iv_bm = bm_atm.loc[idx]['iv'].mean()
        
        backwardation = (iv_fm > iv_bm) if pd.notna(iv_fm) and pd.notna(iv_bm) else np.nan
        
        # ---- Far-OTM Delta (<10Δ calls, >2 DTE) ----
        far_otm = day[(day['side'] == 'CALL') & (day['delta'] > 0) & (day['delta'] <= 0.10) & (day['dte'] > 2)]
        notional_delta = (far_otm['delta'] * far_otm['open_interest'] * 100 * far_otm['underlying_price']).sum()
        
        results.append({
            'date': d, 'ticker': ticker, 'spot': spot,
            'vwks': vwks, 'skew': skew if pd.notna(skew) else np.nan,
            'iv_fm': iv_fm, 'iv_bm': iv_bm, 'backwardation': backwardation,
            'notional_delta': notional_delta
        })

feat = pd.DataFrame(results)
print(f"Features computed: {len(feat)} rows")

# ---- Smooth with 3D MA per ticker ----
feat = feat.sort_values(['ticker','date'])
feat['vwks_3d'] = feat.groupby('ticker')['vwks'].transform(lambda x: x.rolling(3, min_periods=2).mean())
feat['skew_3d'] = feat.groupby('ticker')['skew'].transform(lambda x: x.rolling(3, min_periods=2).mean())
feat['spot_3d'] = feat.groupby('ticker')['spot'].transform(lambda x: x.rolling(3, min_periods=2).mean())
feat['nd_3d'] = feat.groupby('ticker')['notional_delta'].transform(lambda x: x.rolling(3, min_periods=2).mean())

# ---- Gap and spot change ----
feat['gap'] = ((feat['vwks_3d'] - feat['spot_3d']) / feat['spot_3d']) * 100
feat['spot_chg_5d'] = feat.groupby('ticker')['spot'].transform(lambda x: x.pct_change(5))

# ---- Signal definitions ----
# M1: VWKS_3d increasing AND Skew_3d increasing
feat['vwks_rising'] = feat.groupby('ticker')['vwks_3d'].transform(lambda x: x > x.shift(1))
feat['skew_rising'] = feat.groupby('ticker')['skew_3d'].transform(lambda x: x > x.shift(1))
feat['spot_flat'] = feat['spot_chg_5d'].abs() < 0.02
feat['sig_M1'] = feat['vwks_rising'] & feat['skew_rising'] & feat['spot_flat']

# M2: Gap shrinking
feat['gap_shrinking'] = feat.groupby('ticker')['gap'].transform(lambda x: x < x.shift(1))
feat['sig_M2'] = feat['gap_shrinking'] & feat['spot_flat']

# M3: Gap at 80th percentile (computed per ticker over trailing 90 days)
feat['gap_p80'] = feat.groupby('ticker')['gap'].transform(lambda x: x.rolling(90, min_periods=20).quantile(0.80))
feat['sig_M3'] = (feat['gap'] > feat['gap_p80']) & feat['spot_flat']

# M4: Skew rising (part of M1, already captured)
feat['sig_M4'] = feat['skew_rising'] & feat['spot_flat']

# M5: Far-OTM delta increasing (3D MA up) with flat spot
feat['nd_rising'] = feat.groupby('ticker')['nd_3d'].transform(lambda x: x > x.shift(1))
feat['sig_M5'] = feat['nd_rising'] & feat['spot_flat']

# M6: Backwardation (just the flag itself)
feat['sig_M6'] = feat['backwardation']

# ---- Persistence signals (2+ consecutive days) ----
for sig in ['M1','M2','M3','M4','M5']:
    feat[f'sig_{sig}_2d'] = feat.groupby('ticker')[f'sig_{sig}'].transform(
        lambda x: x.rolling(2, min_periods=2).sum() == 2)
    feat[f'sig_{sig}_3d'] = feat.groupby('ticker')[f'sig_{sig}'].transform(
        lambda x: x.rolling(3, min_periods=3).sum() == 3)

# ---- Combinations ----
feat['sig_M1_M5'] = feat['sig_M1'] & feat['sig_M5']
feat['sig_M3_M5'] = feat['sig_M3'] & feat['sig_M5']
feat['sig_M1_M3'] = feat['sig_M1'] & feat['sig_M3']
feat['sig_M1_M3_M5'] = feat['sig_M1'] & feat['sig_M3'] & feat['sig_M5']

# ---- With backwardation filter ----
for sig_base in ['M1','M2','M3','M4','M5','M1_M5','M3_M5','M1_M3','M1_M3_M5']:
    feat[f'sig_{sig_base}_bw'] = feat[f'sig_{sig_base}'] & feat['sig_M6']

print("\nStep 3: Computing forward returns...")
# Get price data
prices = {}
for i in range(0, len(TICKERS), 20):
    chunk = TICKERS[i:i+20]
    data = yf.download(chunk, start='2026-04-01', end='2026-07-09', progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        for t in chunk:
            if ('Close', t) in data.columns:
                prices[t] = data[('Close', t)].dropna()
    if i % 40 == 0:
        print(f"  Prices: {i}/{len(TICKERS)}")

def get_fwd_rets(row, horizon_days):
    t, d = row['ticker'], row['date']
    if t not in prices:
        return np.nan
    s = prices[t]
    # Find closest date
    idx_arr = s.index.get_indexer([pd.Timestamp(d)], method='ffill')
    idx = idx_arr[0] if idx_arr[0] >= 0 else -1
    if idx < 0 or idx + horizon_days >= len(s):
        return np.nan
    # count trading days
    end_idx = min(idx + horizon_days, len(s) - 1)
    return s.iloc[end_idx] / s.iloc[idx] - 1

print("  Computing forward returns...")
for h, label in [(2,'t2'), (5,'t5'), (10,'t10'), (20,'t20')]:
    feat[f'fwd_{label}'] = feat.apply(lambda r: get_fwd_rets(r, h), axis=1)

feat.to_csv('accumulation_features.csv', index=False)
print(f"Saved. Signal counts:")
for col in sorted(feat.columns):
    if col.startswith('sig_') and feat[col].dtype == bool:
        count = feat[col].sum()
        if count > 0:
            print(f"  {col}: {count} signals")
print("Done with feature computation!")
