import pandas as pd, numpy as np, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

feat = pd.read_csv('accumulation_features.csv', parse_dates=['date'])

ret_cols = ['fwd_t2', 'fwd_t5', 'fwd_t10', 'fwd_t20']
sig_groups = {
    'Individual': {
        'M1: VWKS+Skew up + Flat': 'sig_M1',
        'M2: Gap down + Flat': 'sig_M2',
        'M3: Gap>80pct + Flat': 'sig_M3',
        'M4: Skew up + Flat': 'sig_M4',
        'M5: OTM Delta up + Flat': 'sig_M5',
    },
    'Persistence 2-day': {
        'M1 (2d)': 'sig_M1_2d', 'M2 (2d)': 'sig_M2_2d', 'M3 (2d)': 'sig_M3_2d',
        'M4 (2d)': 'sig_M4_2d', 'M5 (2d)': 'sig_M5_2d',
    },
    'Persistence 3-day': {
        'M1 (3d)': 'sig_M1_3d', 'M2 (3d)': 'sig_M2_3d', 'M3 (3d)': 'sig_M3_3d',
        'M4 (3d)': 'sig_M4_3d', 'M5 (3d)': 'sig_M5_3d',
    },
    'Combinations': {
        'M1+M5': 'sig_M1_M5', 'M3+M5': 'sig_M3_M5', 'M1+M3': 'sig_M1_M3', 'M1+M3+M5': 'sig_M1_M3_M5',
    },
}

all_results = []

for group_name, signals in sig_groups.items():
    for sig_name, sig_col in signals.items():
        sig_days = feat[feat[sig_col] == True]
        non_days = feat[feat[sig_col] == False]
        
        for ret in ret_cols:
            sig_ret = sig_days[ret].dropna().mean()
            non_ret = non_days[ret].dropna().mean()
            spread = sig_ret - non_ret
            hit_rate = (sig_days[ret].dropna() > 0).mean()
            sig_vals = sig_days[ret].dropna()
            tstat = sig_vals.mean() / sig_vals.std() * np.sqrt(len(sig_vals)) if len(sig_vals) > 5 else np.nan
            
            all_results.append({
                'group': group_name, 'signal': sig_name, 'horizon': ret,
                'signal_ret': sig_ret, 'baseline_ret': non_ret, 'spread': spread,
                'hit_rate': hit_rate, 'n_signals': len(sig_days), 'tstat': tstat
            })

        # With backwardation filter
        bw_col = f'{sig_col}_bw'
        if bw_col in feat.columns:
            sig_bw = feat[feat[bw_col] == True]
            for ret in ret_cols:
                sig_ret_bw = sig_bw[ret].dropna().mean()
                spread_bw = sig_ret_bw - non_days[ret].dropna().mean()
                hit_bw = (sig_bw[ret].dropna() > 0).mean()
                all_results.append({
                    'group': f'{group_name} + BW', 'signal': f'{sig_name} + BW',
                    'horizon': ret, 'signal_ret': sig_ret_bw, 'baseline_ret': non_days[ret].dropna().mean(),
                    'spread': spread_bw, 'hit_rate': hit_bw, 'n_signals': len(sig_bw), 'tstat': np.nan
                })

results = pd.DataFrame(all_results)

print("=" * 100)
print("MODEL BACKTEST RESULTS - All 66 Tickers")
print("=" * 100)

for group in results['group'].unique():
    grp = results[results['group'] == group]
    if grp['spread'].notna().sum() == 0:
        continue
    print(f"\n--- {group} ---")
    header = f"  {'Signal':<28s} {'t2':>10s} {'t5':>10s} {'t10':>10s} {'t20':>10s}  {'n_sig':>6s}"
    print(header)
    print("  " + "-" * 80)
    
    sigs = sorted(grp['signal'].unique())
    for sig in sigs:
        sub = grp[grp['signal'] == sig]
        row = f"  {sig:<28s}"
        for h in ['fwd_t2', 'fwd_t5', 'fwd_t10', 'fwd_t20']:
            s = sub[sub['horizon'] == h]
            if len(s) > 0 and pd.notna(s['spread'].values[0]):
                row += f" {s['spread'].values[0]:>+8.2%}"
                hit = s['hit_rate'].values[0]
                if pd.notna(hit):
                    row += f"({hit:.0%})"
                else:
                    row += "     "
            else:
                row += " " * 10
        n = sub['n_signals'].values[0] if len(sub) > 0 else 0
        row += f"  {n:>5d}"
        print(row)

# Save for Notion
results.to_csv('backtest_results.csv', index=False)
print("\nSaved backtest_results.csv")
