import pandas as pd, numpy as np, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

results = pd.read_csv('backtest_results.csv')
feat = pd.read_csv('accumulation_features.csv', parse_dates=['date'])

# What was the baseline?
print("BASELINE RETURNS (all non-signal days):")
for ret in ['fwd_t2', 'fwd_t5', 'fwd_t10', 'fwd_t20']:
    vals = feat[ret].dropna()
    print(f"  {ret}: mean={vals.mean():+.2%}  median={vals.median():+.2%}  positive={((vals>0).mean()):.0%}  n={len(vals)}")

print("\nTOP SIGNALS BY ABSOLUTE RETURN (t10):")
t10 = results[results['horizon'] == 'fwd_t10'].dropna(subset=['signal_ret'])
t10 = t10.sort_values('signal_ret', ascending=False)
print(f"{'Signal':<40s} {'t10_ret':>8s} {'hit':>6s} {'spread':>8s} {'n':>5s}")
print("-" * 70)
for _, row in t10.head(20).iterrows():
    print(f"{row['signal']:<40s} {row['signal_ret']:>+7.2%} {row['hit_rate']:>5.0%} {row['spread']:>+7.2%} {row['n_signals']:>5.0f}")

print("\nTOP SIGNALS BY ABSOLUTE RETURN (t20):")
t20 = results[results['horizon'] == 'fwd_t20'].dropna(subset=['signal_ret'])
t20 = t20.sort_values('signal_ret', ascending=False)
print(f"{'Signal':<40s} {'t20_ret':>8s} {'hit':>6s} {'spread':>8s} {'n':>5s}")
print("-" * 70)
for _, row in t20.head(20).iterrows():
    print(f"{row['signal']:<40s} {row['signal_ret']:>+7.2%} {row['hit_rate']:>5.0%} {row['spread']:>+7.2%} {row['n_signals']:>5.0f}")

print("\n--- BEST BY HIT RATE (t10, min 20 signals) ---")
t10_filt = t10[t10['n_signals'] >= 20].sort_values('hit_rate', ascending=False)
for _, row in t10_filt.head(15).iterrows():
    print(f"{row['signal']:<40s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} spread={row['spread']:+.2%} n={row['n_signals']:.0f}")

print("\n--- BEST BY HIT RATE (t20, min 20 signals) ---")
t20_filt = t20[t20['n_signals'] >= 20].sort_values('hit_rate', ascending=False)
for _, row in t20_filt.head(15).iterrows():
    print(f"{row['signal']:<40s} ret={row['signal_ret']:+.2%} hit={row['hit_rate']:.0%} spread={row['spread']:+.2%} n={row['n_signals']:.0f}")

# Test: what if we drop the "flat spot" filter? Just raw signals
print("\n--- RAW SIGNALS (no flat spot filter) ---")
feat['raw_M1'] = feat['vwks_rising'] & feat['skew_rising']
feat['raw_M2'] = feat['gap_shrinking']
feat['raw_M4'] = feat['skew_rising']
feat['raw_M5'] = feat['nd_rising']

for name, col in [('Raw M1', 'raw_M1'), ('Raw M2', 'raw_M2'), ('Raw M4', 'raw_M4'), ('Raw M5', 'raw_M5')]:
    sig = feat[feat[col] == True]
    non = feat[feat[col] == False]
    for h in ['fwd_t5','fwd_t10','fwd_t20']:
        s = sig[h].dropna().mean()
        b = non[h].dropna().mean()
        hr = (sig[h].dropna() > 0).mean()
        print(f"  {name:<12s} {h}: ret={s:+.2%} spread={s-b:+.2%} hit={hr:.0%} n={len(sig)}")

# Check: does flat spot even help? Compare M5 with/without flat spot
print("\n--- M5: Flat spot vs No filter ---")
for name, col in [('M5+flat', 'sig_M5'), ('M5 raw', 'raw_M5')]:
    sig = feat[feat[col] == True]
    for h in ['fwd_t5','fwd_t10','fwd_t20']:
        s = sig[h].dropna().mean()
        hr = (sig[h].dropna() > 0).mean()
        print(f"  {name:<12s} {h}: ret={s:+.2%} hit={hr:.0%} n={len(sig)}")

print("\nDone!")
