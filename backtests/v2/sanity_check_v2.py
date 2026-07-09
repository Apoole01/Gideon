import pandas as pd, numpy as np
import yfinance as yf

# Load V2 features
feat = pd.read_csv(r'C:\Users\GideonAdmin\.openclaw\workspace\accumulation_features_v2.csv', parse_dates=['date'])
results = pd.read_csv(r'C:\Users\GideonAdmin\.openclaw\workspace\backtest_v2_results.csv')

print("=" * 60)
print("SANITY CHECKS — V2 Backtest")
print("=" * 60)

# CHECK 1: Earnings
print("\n1. EARNINGS EXCLUSION")
print(f"   near_earnings sum: {feat['near_earnings'].sum()}")
print(f"   near_earnings dtype: {feat['near_earnings'].dtype}")
n_dates = feat['date'].nunique()
print(f"   Unique dates: {n_dates} ({feat['date'].min()} to {feat['date'].max()})")

# Debug: test earnings for a few tickers
for ticker in ['AAPL', 'MSFT', 'NVDA', 'TSLA']:
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is not None and len(ed) > 0:
            dates_in_range = [d for d in pd.to_datetime(ed.index).date 
                            if pd.Timestamp('2026-04-15').date() <= d <= pd.Timestamp('2026-07-09').date()]
            print(f"   {ticker}: {len(ed)} total earnings, {len(dates_in_range)} in our date range")
            if dates_in_range:
                print(f"     Dates: {dates_in_range[:5]}")
        else:
            print(f"   {ticker}: earnings_dates returned None or empty")
    except Exception as e:
        print(f"   {ticker}: ERROR — {e}")

# CHECK 2: Spot filter
print("\n2. SPOT FILTER COMPARISON")
feat_old_flat = feat['spot_chg_5d'].abs() < 0.02
feat_new_not_spiked = feat['spot_chg_5d'].abs() < 0.05
print(f"   Old flat (<2%): {feat_old_flat.sum()} days ({feat_old_flat.mean():.1%})")
print(f"   New not-spiked (<5%): {feat_new_not_spiked.sum()} days ({feat_new_not_spiked.mean():.1%})")
print(f"   Spot chg_5d distribution: min={feat['spot_chg_5d'].min():.3%} max={feat['spot_chg_5d'].max():.3%}")

# CHECK 3: Signal counts
print("\n3. KEY SIGNAL COUNTS")
key_sigs = ['sig_M1','sig_M7','sig_M3_p90_w90','sig_M3_p95_w90','raw_M1_M5_M7','sig_M1_M5_M7_bw_5pct']
for sc in key_sigs:
    n = feat[sc].sum()
    print(f"   {sc}: {n} signals")

# CHECK 4: M3 signals — verify percentile logic
print("\n4. M3 PERCENTILE SANITY")
# Pick a ticker and verify p90_w90
ticker = 'AAPL'
aapl = feat[feat['ticker'] == ticker].sort_values('date').tail(30)
print(f"   {ticker} last 30 days:")
print(f"   gap range: {aapl['gap'].min():.2f}% to {aapl['gap'].max():.2f}%")
print(f"   gap_p90_w90 range: {aapl['gap_p90_w90'].min():.2f}% to {aapl['gap_p90_w90'].max():.2f}%")
sig_aapl = aapl[aapl['sig_M3_p90_w90'] == True]
print(f"   sig_M3_p90_w90 fires: {len(sig_aapl)}")
for _, r in sig_aapl.iterrows():
    print(f"     {r['date'].date()}: gap={r['gap']:.2f}% > p90={r['gap_p90_w90']:.2f}%")

# CHECK 5: Return distributions for top signal
print("\n5. M3_P90_W90 RETURN DISTRIBUTION")
m3_sig = feat[feat['sig_M3_p90_w90'] == True]
for h in ['fwd_t2','fwd_t5','fwd_t7','fwd_t10','fwd_t20']:
    vals = m3_sig[h].dropna()
    if len(vals) > 0:
        print(f"   {h}: mean={vals.mean():+.2%} median={vals.median():+.2%} std={vals.std():.2%} min={vals.min():+.2%} max={vals.max():+.2%} n={len(vals)}")
        print(f"       >0: {(vals>0).mean():.0%}  >=0: {(vals>=0).mean():.0%}  >+5%: {(vals>0.05).mean():.0%}")

# CHECK 6: Put VWKS validity
print("\n6. PUT VWKS DATA QUALITY")
print(f"   vwks_put NaN: {feat['vwks_put'].isna().sum()} ({feat['vwks_put'].isna().mean():.1%})")
print(f"   vwks_put_3d NaN: {feat['vwks_put_3d'].isna().sum()} ({feat['vwks_put_3d'].isna().mean():.1%})")
# How many put VWKS falling flags are there?
feat_valid = feat[feat['vwks_put_3d'].notna()]
print(f"   Valid put VWKS rows: {len(feat_valid)}")
if len(feat_valid) > 0:
    n_falling = (feat_valid.groupby('ticker')['vwks_put_3d'].transform(lambda x: x < x.shift(1)) == True).sum()
    print(f"   vwks_put_falling: {n_falling} occurrences")

# CHECK 7: BW magnitude tiers — verify nesting
print("\n7. BW MAGNITUDE TIER COUNTS")
for tier in ['sig_M6_binary','bw_mag_1pct','bw_mag_2pct','bw_mag_3pct','bw_mag_5pct']:
    n = feat[tier].sum()
    print(f"   {tier}: {n} ({n/len(feat):.1%})")

# CHECK 8: Verify no look-ahead — signals use only t-day data
print("\n8. NO LOOK-AHEAD CHECK")
# Verify gap_p90_w90 uses rolling window
sample = feat[(feat['ticker']=='AAPL') & (feat['sig_M3_p90_w90']==True)].head(3)
for _, r in sample.iterrows():
    d = r['date']
    # Get all AAPL data up to this date
    hist = feat[(feat['ticker']=='AAPL') & (feat['date'] <= d)].sort_values('date')
    gaps = hist['gap'].dropna().tail(90)
    p90 = gaps.quantile(0.90) if len(gaps) >= 20 else np.nan
    actual_gap = r['gap']
    computed_p90 = r['gap_p90_w90']
    print(f"   {d.date()}: gap={actual_gap:.2f}%  computed_p90={computed_p90:.2f}%  manual_p90={p90:.2f}%  match={abs(computed_p90-p90)<0.01}")

print("\n" + "=" * 60)
print("CHECKS COMPLETE")
