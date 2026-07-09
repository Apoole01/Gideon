"""
V2 Backtest — Accumulation Models
Changes:
  1. Flat spot → spot NOT spiked (abs 5d < 5%)
  2. M3 grid search: 75-95% ile × 30-90d windows
  3. Backwardation magnitude tiers
  4. Earnings exclusion
  5. Put VWKS + combo test
"""
import os, sys, io, json, warnings, time
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import boto3, pyarrow.parquet as pq
import pandas as pd, numpy as np
import yfinance as yf

from dotenv import load_dotenv
load_dotenv(r'C:\Users\GideonAdmin\.openclaw\workspace\.env')

s3 = boto3.client('s3', region_name='us-east-2')
BUCKET = 'options-data-lake-639098881709-us-east-2-an'

TICKERS = ['AAPL','NVDA','TSLA','AMD','MSFT','AMZN','META','GOOGL','NFLX','COIN','PLTR',
'BABA','DIS','JPM','BAC','C','WFC','GS','MS','V','MA','JNJ','UNH','LLY','MRK','ABBV',
'XOM','CVX','WMT','TGT','COST','HD','LOW','MCD','SBUX','NKE','KO','PEP','PG','GM',
'UBER','ABNB','DAL','UAL','RCL','ROKU','PYPL','HOOD','SNOW','CRWD','PANW','DDOG',
'ENPH','MSTR','MU','INTC','TSM','QCOM','AVGO','TXN','CRM','ADBE','NOW','UPST','AFRM','BA']

print("="*80)
print("V2 BACKTEST — Accumulation Models Enhanced")
print("="*80)

# ═══════════════════════════════════════════════════════════
# STEP 1: Load and clean S3 data
# ═══════════════════════════════════════════════════════════
print("\n[1/8] Loading enriched chain from S3...")
t0 = time.time()
resp = s3.get_object(Bucket=BUCKET, Key='dashboard_data/enriched_chain_gold.parquet')
table = pq.read_table(io.BytesIO(resp['Body'].read()))
df = table.to_pandas()
df['date'] = pd.to_datetime(df['timestamp']).dt.date
df['date'] = pd.to_datetime(df['date'])
df = df[df['ticker'].isin(TICKERS)]
print(f"  {len(df):,} rows, {df['ticker'].nunique()} tickers, {df['date'].nunique()} dates")

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
print(f"  Cleaned. {len(df):,} rows remaining ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 2: Compute daily features per ticker (CALL + PUT VWKS)
# ═══════════════════════════════════════════════════════════
print("\n[2/8] Computing daily features...")
t0 = time.time()
results = []

for ticker in TICKERS:
    td = df[df['ticker'] == ticker].sort_values('date')
    if td.empty: continue
    dates = sorted(td['date'].unique())
    
    for d in dates:
        day = td[td['date'] == d]
        if day.empty: continue
        spot = day['underlying_price'].iloc[0]
        
        # CALL VWKS (7-45 DTE)
        calls_fm = day[(day['side'] == 'CALL') & (day['dte'].between(7, 45))]
        vwks_call = np.nan
        if not calls_fm.empty and calls_fm['volume'].sum() > 0:
            vwks_call = (calls_fm['strike'] * calls_fm['volume']).sum() / calls_fm['volume'].sum()
        
        # PUT VWKS (7-45 DTE)
        puts_fm = day[(day['side'] == 'PUT') & (day['dte'].between(7, 45))]
        vwks_put = np.nan
        if not puts_fm.empty and puts_fm['volume'].sum() > 0:
            vwks_put = (puts_fm['strike'] * puts_fm['volume']).sum() / puts_fm['volume'].sum()
        
        # Skew (7-60 DTE, 25Δ)
        skew_scope = day[(day['dte'].between(7, 60)) & (day['iv'] > 0) & (day['iv'] < 2.0)]
        c25 = skew_scope[(skew_scope['side'] == 'CALL') & (skew_scope['delta'].between(0.20, 0.30))]['iv'].mean()
        p25 = skew_scope[(skew_scope['side'] == 'PUT') & (skew_scope['delta'].between(-0.30, -0.20))]['iv'].mean()
        skew = (c25 - p25) if pd.notna(c25) and pd.notna(p25) else np.nan
        
        # Backwardation (binary + magnitude)
        atm_c = day[(day['side'] == 'CALL') & (day['iv'] > 0) & (day['iv'] < 2.0)].copy()
        atm_c['strike_dist'] = (atm_c['strike'] - spot).abs()
        
        fm_atm = atm_c[atm_c['dte'].between(7, 45)]
        bm_atm = atm_c[atm_c['dte'] > 45]
        
        iv_fm = np.nan; iv_bm = np.nan
        if not fm_atm.empty:
            idx = fm_atm.groupby('expiration')['strike_dist'].idxmin()
            iv_fm = fm_atm.loc[idx]['iv'].mean()
        if not bm_atm.empty:
            idx = bm_atm.groupby('expiration')['strike_dist'].idxmin()
            iv_bm = bm_atm.loc[idx]['iv'].mean()
        
        bw_bool = (iv_fm > iv_bm) if pd.notna(iv_fm) and pd.notna(iv_bm) else np.nan
        bw_magnitude = (iv_fm - iv_bm) if pd.notna(iv_fm) and pd.notna(iv_bm) else np.nan
        
        # Far-OTM Delta
        far_otm = day[(day['side'] == 'CALL') & (day['delta'] > 0) & (day['delta'] <= 0.10) & (day['dte'] > 2)]
        notional_delta = (far_otm['delta'] * far_otm['open_interest'] * 100 * far_otm['underlying_price']).sum()
        
        results.append({
            'date': d, 'ticker': ticker, 'spot': spot,
            'vwks_call': vwks_call, 'vwks_put': vwks_put,
            'skew': skew, 'iv_fm': iv_fm, 'iv_bm': iv_bm,
            'backwardation': bw_bool, 'bw_magnitude': bw_magnitude,
            'notional_delta': notional_delta
        })

feat = pd.DataFrame(results)
print(f"  Features: {len(feat)} rows ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 3: Smoothing & Derived
# ═══════════════════════════════════════════════════════════
print("\n[3/8] Smoothing & derived features...")
t0 = time.time()
feat = feat.sort_values(['ticker','date'])

def smooth(grp, col, window=3, minp=2):
    return grp[col].rolling(window, min_periods=minp).mean()

feat['vwks_3d'] = feat.groupby('ticker').apply(lambda g: smooth(g, 'vwks_call')).reset_index(level=0, drop=True)
feat['vwks_put_3d'] = feat.groupby('ticker').apply(lambda g: smooth(g, 'vwks_put')).reset_index(level=0, drop=True)
feat['skew_3d'] = feat.groupby('ticker').apply(lambda g: smooth(g, 'skew')).reset_index(level=0, drop=True)
feat['spot_3d'] = feat.groupby('ticker').apply(lambda g: smooth(g, 'spot')).reset_index(level=0, drop=True)
feat['nd_3d'] = feat.groupby('ticker').apply(lambda g: smooth(g, 'notional_delta')).reset_index(level=0, drop=True)

feat['gap'] = ((feat['vwks_3d'] - feat['spot_3d']) / feat['spot_3d']) * 100
feat['spot_chg_5d'] = feat.groupby('ticker')['spot'].transform(lambda x: x.pct_change(5))

# Directional flags
feat['vwks_rising'] = feat.groupby('ticker')['vwks_3d'].transform(lambda x: x > x.shift(1))
feat['vwks_put_rising'] = feat.groupby('ticker')['vwks_put_3d'].transform(lambda x: x > x.shift(1))
feat['vwks_put_falling'] = feat.groupby('ticker')['vwks_put_3d'].transform(lambda x: x < x.shift(1))
feat['skew_rising'] = feat.groupby('ticker')['skew_3d'].transform(lambda x: x > x.shift(1))
feat['nd_rising'] = feat.groupby('ticker')['nd_3d'].transform(lambda x: x > x.shift(1))
feat['gap_shrinking'] = feat.groupby('ticker')['gap'].transform(lambda x: x < x.shift(1))

# NEW: spot not spiked (<5%) replaces flat spot (<2%)
feat['spot_not_spiked'] = feat['spot_chg_5d'].abs() < 0.05

# OLD flat spot for comparison
feat['spot_flat_old'] = feat['spot_chg_5d'].abs() < 0.02

print(f"  Done ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 4: Signal Definitions
# ═══════════════════════════════════════════════════════════
print("\n[4/8] Defining signals...")
t0 = time.time()

# --- Base Signals (using NEW spot_not_spiked) ---
feat['sig_M1'] = feat['vwks_rising'] & feat['skew_rising'] & feat['spot_not_spiked']
feat['sig_M2'] = feat['gap_shrinking'] & feat['spot_not_spiked']
feat['sig_M4'] = feat['skew_rising'] & feat['spot_not_spiked']
feat['sig_M5'] = feat['nd_rising'] & feat['spot_not_spiked']
feat['sig_M6_binary'] = feat['backwardation']

# --- Raw signals (NO spot filter at all) ---
feat['raw_M1'] = feat['vwks_rising'] & feat['skew_rising']
feat['raw_M5'] = feat['nd_rising']

# --- PUT VWKS signals ---
# M7: Call VWKS rising + Put VWKS falling (dual accumulation — calls shifting up, puts shifting down)
feat['sig_M7'] = feat['vwks_rising'] & feat['vwks_put_falling'] & feat['spot_not_spiked']
feat['raw_M7'] = feat['vwks_rising'] & feat['vwks_put_falling']

# M8: Call VWKS rising + Put VWKS rising (calls AND puts shifting up — hedging, not accumulation)
feat['sig_M8'] = feat['vwks_rising'] & feat['vwks_put_rising'] & feat['spot_not_spiked']

# --- Backwardation magnitude tiers ---
feat['bw_mag_1pct'] = feat['bw_magnitude'] >= 0.01  # 1% front premium
feat['bw_mag_2pct'] = feat['bw_magnitude'] >= 0.02  # 2% front premium
feat['bw_mag_3pct'] = feat['bw_magnitude'] >= 0.03  # 3% front premium
feat['bw_mag_5pct'] = feat['bw_magnitude'] >= 0.05  # 5% front premium

# --- M3 GRID: Percentile variants ---
PERCENTILES = [0.75, 0.80, 0.85, 0.90, 0.95]
WINDOWS = [30, 45, 60, 90]

m3_signals = {}
for pct in PERCENTILES:
    for win in WINDOWS:
        col_name = f'gap_p{pct*100:.0f}_w{win}'
        feat[col_name] = feat.groupby('ticker')['gap'].transform(
            lambda x, w=win, p=pct: x.rolling(w, min_periods=max(10, w//3)).quantile(p))
        sig_name = f'sig_M3_p{pct*100:.0f}_w{win}'
        m3_signals[sig_name] = (feat['gap'] > feat[col_name]) & feat['spot_not_spiked']
        feat[sig_name] = m3_signals[sig_name]

# Also test M3 variants WITHOUT spot filter for comparison
for pct in PERCENTILES:
    for win in WINDOWS:
        col_name = f'gap_p{pct*100:.0f}_w{win}'
        sig_name = f'raw_M3_p{pct*100:.0f}_w{win}'
        feat[sig_name] = feat['gap'] > feat[col_name]

# --- Combos ---
feat['sig_M1_M5'] = feat['sig_M1'] & feat['sig_M5']
feat['sig_M1_M7'] = feat['sig_M1'] & feat['sig_M7']
feat['sig_M5_M7'] = feat['sig_M5'] & feat['sig_M7']
feat['sig_M1_M5_M7'] = feat['sig_M1'] & feat['sig_M5'] & feat['sig_M7']

# Raw combos (no spot filter)
feat['raw_M1_M5'] = feat['raw_M1'] & feat['raw_M5']
feat['raw_M1_M7'] = feat['raw_M1'] & feat['raw_M7']
feat['raw_M5_M7'] = feat['raw_M5'] & feat['raw_M7']
feat['raw_M1_M5_M7'] = feat['raw_M1'] & feat['raw_M5'] & feat['raw_M7']

# --- BW overlay for key signals ---
for sig_base in ['M1','M5','M7','M1_M5','M1_M7','M1_M5_M7']:
    feat[f'sig_{sig_base}_bw'] = feat[f'sig_{sig_base}'] & feat['sig_M6_binary']
    feat[f'raw_{sig_base}_bw'] = feat[f'raw_{sig_base}'] & feat['sig_M6_binary']
    # Magnitude tiers
    for tier in ['1pct','2pct','3pct','5pct']:
        feat[f'sig_{sig_base}_bw_{tier}'] = feat[f'sig_{sig_base}'] & feat[f'bw_mag_{tier}']
        feat[f'raw_{sig_base}_bw_{tier}'] = feat[f'raw_{sig_base}'] & feat[f'bw_mag_{tier}']

print(f"  {sum(1 for c in feat.columns if c.startswith('sig_'))} signal columns defined ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 5: Earnings data
# ═══════════════════════════════════════════════════════════
print("\n[5/8] Fetching earnings dates...")
t0 = time.time()

earnings_dates = {}
# Fetch for each ticker
for i, ticker in enumerate(TICKERS):
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is not None and len(ed) > 0:
            # earnings_dates returns a DataFrame with datetime index
            earnings_dates[ticker] = set(pd.to_datetime(ed.index).date)
        else:
            earnings_dates[ticker] = set()
    except Exception:
        earnings_dates[ticker] = set()
    if (i+1) % 10 == 0:
        print(f"  Earnings: {i+1}/{len(TICKERS)} tickers...")

# Create earnings-proximity mask (±3 days from earnings)
print("  Building earnings exclusion mask...")
feat['near_earnings'] = False
for ticker in TICKERS:
    if ticker not in earnings_dates or not earnings_dates[ticker]:
        continue
    ticker_earnings = earnings_dates[ticker]
    ticker_mask = feat['ticker'] == ticker
    ticker_dates = feat.loc[ticker_mask, 'date']
    for edate in ticker_earnings:
        # Flag dates within ±3 calendar days of earnings
        window_start = pd.Timestamp(edate) - pd.Timedelta(days=3)
        window_end = pd.Timestamp(edate) + pd.Timedelta(days=3)
        in_window = (ticker_dates >= window_start) & (ticker_dates <= window_end)
        feat.loc[ticker_mask & feat['date'].isin(ticker_dates[in_window]), 'near_earnings'] = True

n_earnings_flagged = feat['near_earnings'].sum()
print(f"  Flagged {n_earnings_flagged} ticker-dates near earnings ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 6: Forward returns
# ═══════════════════════════════════════════════════════════
print("\n[6/8] Computing forward returns (yfinance)...")
t0 = time.time()

prices = {}
for i in range(0, len(TICKERS), 20):
    chunk = TICKERS[i:i+20]
    data = yf.download(chunk, start='2026-03-15', end='2026-07-10', progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        for t in chunk:
            if ('Close', t) in data.columns:
                prices[t] = data[('Close', t)].dropna()
    print(f"  Prices: {i+len(chunk)}/{len(TICKERS)}")

def get_fwd_rets(row, horizon_days):
    t, d = row['ticker'], row['date']
    if t not in prices: return np.nan
    s = prices[t]
    idx_arr = s.index.get_indexer([pd.Timestamp(d)], method='ffill')
    idx = idx_arr[0] if idx_arr[0] >= 0 else -1
    if idx < 0 or idx + horizon_days >= len(s): return np.nan
    return s.iloc[idx + horizon_days] / s.iloc[idx] - 1

for h, label in [(2,'t2'), (5,'t5'), (7,'t7'), (10,'t10'), (20,'t20')]:
    feat[f'fwd_{label}'] = feat.apply(lambda r: get_fwd_rets(r, h), axis=1)

print(f"  Done ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 7: Evaluation function
# ═══════════════════════════════════════════════════════════
print("\n[7/8] Evaluating all signals...")
t0 = time.time()

def evaluate(sig_col, df, exclude_earnings=True):
    """Evaluate a signal column. Returns dict of metrics per horizon."""
    # Determine which data to use
    if exclude_earnings:
        mask = df['near_earnings'] == False
        sig_idx = df[(df[sig_col] == True) & mask]
        non_idx = df[(df[sig_col] == False) & mask]
    else:
        sig_idx = df[df[sig_col] == True]
        non_idx = df[df[sig_col] == False]
    
    results = {}
    for ret in ['fwd_t2','fwd_t5','fwd_t7','fwd_t10','fwd_t20']:
        s = sig_idx[ret].dropna()
        b = non_idx[ret].dropna()
        if len(s) < 5:
            results[ret] = {'ret': np.nan, 'baseline': b.mean(), 'spread': np.nan, 
                           'hit': np.nan, 'not_down': np.nan, 'n': len(s),
                           'win_loss': np.nan, 'max_dd': np.nan, 'sharpe': np.nan}
            continue
        
        pos = s[s > 0]
        neg = s[s < 0]
        win_loss = len(pos) / len(neg) if len(neg) > 0 else float('inf')
        
        # Max drawdown (cumulative)
        cum = (1 + s).cumprod()
        peak = cum.expanding().max()
        max_dd = ((cum / peak) - 1).min()
        
        results[ret] = {
            'ret': s.mean(),
            'baseline': b.mean(),
            'spread': s.mean() - b.mean(),
            'hit': (s > 0).mean(),           # >0%
            'not_down': (s >= 0).mean(),     # >=0 (for put spread selling)
            'n': len(s),
            'win_loss': win_loss,
            'max_dd': max_dd,
            'sharpe': s.mean() / s.std() if s.std() > 0 else 0
        }
    return results

# Collect all signal columns to evaluate
sig_cols = [c for c in feat.columns if (c.startswith('sig_') or c.startswith('raw_')) 
            and feat[c].dtype == bool]

# Also add backwardation magnitude tiers (standalone)
bw_tier_cols = ['bw_mag_1pct', 'bw_mag_2pct', 'bw_mag_3pct', 'bw_mag_5pct']

all_sigs = sig_cols + bw_tier_cols

all_results = []
for sc in all_sigs:
    if feat[sc].sum() < 3:  # Skip signals with <3 fires
        continue
    res = evaluate(sc, feat, exclude_earnings=True)
    # Also evaluate without earnings filter for comparison
    res_noearn = evaluate(sc, feat, exclude_earnings=False)
    
    for ret in res:
        r = res[ret]
        all_results.append({
            'signal': sc,
            'horizon': ret,
            'signal_ret': r['ret'],
            'baseline_ret': r['baseline'],
            'spread': r['spread'],
            'hit_rate': r['hit'],
            'not_down_rate': r['not_down'],
            'n_signals': r['n'],
            'win_loss_ratio': r['win_loss'],
            'max_drawdown': r['max_dd'],
            'sharpe': r['sharpe'],
            # Weekly signal frequency
            'signals_per_week': r['n'] / 8.14,  # 57 days / 7
        })

results_df = pd.DataFrame(all_results)
results_df.to_csv('backtest_v2_results.csv', index=False)
feat.to_csv('accumulation_features_v2.csv', index=False)  # Save for later
print(f"  Evaluated {len(all_sigs)} signals, {len(results_df)} rows ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════
# STEP 8: Analysis & Reporting
# ═══════════════════════════════════════════════════════════
print("\n[8/8] Analysis & Reporting...")
print("="*80)

# --- M3 GRID SEARCH RESULTS ---
print("\n--- M3 PERCENTILE GRID SEARCH (t10, with spot filter) ---")
m3_grid = results_df[(results_df['signal'].str.startswith('sig_M3_p')) & (results_df['horizon'] == 'fwd_t10')]
m3_grid = m3_grid.dropna(subset=['hit_rate'])
m3_grid = m3_grid.sort_values('hit_rate', ascending=False)
print(f"{'Signal':<25s} {'t10_ret':>8s} {'hit':>6s} {'not_down':>9s} {'spread':>8s} {'n':>5s}")
for _, row in m3_grid.head(20).iterrows():
    print(f"{row['signal']:<25s} {row['signal_ret']:>+7.2%} {row['hit_rate']:>5.0%} {row['not_down_rate']:>8.0%} {row['spread']:>+7.2%} {row['n_signals']:>5.0f}")

# Best M3 by hit rate at each horizon
print("\n--- BEST M3 CONFIG BY HORIZON ---")
for h in ['fwd_t2','fwd_t5','fwd_t7','fwd_t10','fwd_t20']:
    m3_h = results_df[(results_df['signal'].str.startswith('sig_M3_p')) & (results_df['horizon'] == h)]
    best = m3_h.dropna(subset=['hit_rate']).sort_values('hit_rate', ascending=False).head(3)
    print(f"\n  {h}:")
    for _, row in best.iterrows():
        print(f"    {row['signal']:<25s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} nd={row['not_down_rate']:.0%} n={row['n_signals']:.0f}")

# --- BEST OVERALL SIGNALS (by hit rate, t10) ---
print("\n\n--- TOP 20 SIGNALS BY HIT RATE (t10, min 20 signals) ---")
t10_signals = results_df[(results_df['horizon'] == 'fwd_t10') & (results_df['n_signals'] >= 20)]
t10_signals = t10_signals.dropna(subset=['hit_rate']).sort_values('hit_rate', ascending=False)
for _, row in t10_signals.head(20).iterrows():
    print(f"  {row['signal']:<35s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} nd={row['not_down_rate']:.0%} spread={row['spread']:+.2%} n={row['n_signals']:.0f}")

# --- BEST BY NOT-DOWN RATE (t10) ---
print("\n\n--- TOP 15 BY NOT-DOWN RATE (t10, min 20 signals) [Put Spread Selling] ---")
nd10 = results_df[(results_df['horizon'] == 'fwd_t10') & (results_df['n_signals'] >= 20)]
nd10 = nd10.dropna(subset=['not_down_rate']).sort_values('not_down_rate', ascending=False)
for _, row in nd10.head(15).iterrows():
    print(f"  {row['signal']:<35s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} nd={row['not_down_rate']:.0%} spread={row['spread']:+.2%} n={row['n_signals']:.0f}")

# --- BACKWARDATION MAGNITUDE ANALYSIS ---
print("\n\n--- BACKWARDATION MAGNITUDE IMPACT ---")
bw_tiers = results_df[(results_df['signal'].isin(['sig_M6_binary','bw_mag_1pct','bw_mag_2pct','bw_mag_3pct','bw_mag_5pct'])) & (results_df['horizon'] == 'fwd_t10')]
for _, row in bw_tiers.iterrows():
    print(f"  {row['signal']:<20s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} nd={row['not_down_rate']:.0%} n={row['n_signals']:.0f}")

# Compare best signals WITH vs WITHOUT earnings exclusion
print("\n\n--- EARNINGS EXCLUSION IMPACT (top signals) ---")
for sc in ['raw_M5', 'raw_M1_M5_M7_bw', 'sig_M1_M5_M7']:
    if sc not in feat.columns:
        continue
    r_with = evaluate(sc, feat, exclude_earnings=True)
    r_without = evaluate(sc, feat, exclude_earnings=False)
    for h in ['fwd_t10','fwd_t20']:
        w = r_with[h]
        wo = r_without[h]
        print(f"  {sc:<30s} {h}: with_excl hit={w['hit']:.0%}(n={w['n']:.0f}) | no_excl hit={wo['hit']:.0%}(n={wo['n']:.0f})")

# --- PUT VWKS ANALYSIS ---
print("\n\n--- PUT VWKS IMPACT (M1 vs M7 vs M8) ---")
vwks_compare = results_df[(results_df['signal'].isin(['sig_M1','sig_M7','sig_M8','sig_M1_M7','raw_M7'])) & (results_df['horizon'] == 'fwd_t10')]
for _, row in vwks_compare.dropna(subset=['hit_rate']).sort_values('hit_rate', ascending=False).iterrows():
    print(f"  {row['signal']:<25s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} nd={row['not_down_rate']:.0%} n={row['n_signals']:.0f}")

# --- Quality Signals Summary (high conviction, low frequency) ---
print("\n\n--- QUALITY SIGNALS (hit > 60%, 20-150 signals, t10) ---")
quality = results_df[(results_df['horizon'] == 'fwd_t10') & (results_df['n_signals'] >= 20) & (results_df['n_signals'] <= 150)]
quality = quality.dropna(subset=['hit_rate'])
quality = quality[quality['hit_rate'] > 0.60].sort_values('hit_rate', ascending=False)
for _, row in quality.iterrows():
    print(f"  {row['signal']:<35s} hit={row['hit_rate']:.0%} nd={row['not_down_rate']:.0%} ret={row['signal_ret']:+.2%} n={row['n_signals']:.0f} wl={row['win_loss_ratio']:.1f}")

print("\n" + "="*80)
print("DONE! Results saved to backtest_v2_results.csv")
print(f"Features saved to accumulation_features_v2.csv")
