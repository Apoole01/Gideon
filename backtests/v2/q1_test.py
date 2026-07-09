"""M3_p90_w90 Q1-filtered + stop loss test"""
import pandas as pd, numpy as np

feat = pd.read_csv(r'C:\Users\GideonAdmin\.openclaw\workspace\accumulation_features_v2.csv', parse_dates=['date'])

# Base M3 signal (earnings excluded)
sig = feat[(feat['sig_M3_p90_w90'] == True) & (feat['near_earnings'] == False)].copy()

# Compute gap quartile thresholds from the signal set
gap_q1_threshold = sig['gap'].quantile(0.25)
gap_q4_threshold = sig['gap'].quantile(0.75)

print(f"M3_p90_w90 gap quantiles:")
print(f"  Q1 (0-25%): gap < {gap_q1_threshold:.2f}%")
print(f"  Q2 (25-50%): {gap_q1_threshold:.2f}% to {sig['gap'].quantile(0.50):.2f}%")
print(f"  Q3 (50-75%): {sig['gap'].quantile(0.50):.2f}% to {gap_q4_threshold:.2f}%")
print(f"  Q4 (75-100%): gap > {gap_q4_threshold:.2f}%")

# Split
q1 = sig[sig['gap'] < gap_q1_threshold]
q234 = sig[sig['gap'] >= gap_q1_threshold]

print(f"\nSignal counts: Q1={len(q1)}, Q2-4={len(q234)}, All={len(sig)}")

# Evaluate: Q1 only, with and without stop loss
print("\n" + "=" * 70)
print("Q1-ONLY M3_p90_w90 — with -2% stop loss")
print("=" * 70)

for horizon, label in [('fwd_t5','t5'), ('fwd_t7','t7'), ('fwd_t10','t10'), ('fwd_t20','t20')]:
    print(f"\n{'='*70}")
    print(f"HORIZON: {label}")
    print(f"{'='*70}")
    
    # Q1 — no stop
    s = q1[horizon].dropna()
    if len(s) < 3:
        print(f"  Too few signals: {len(s)}")
        continue
    
    raw_ret = s.mean()
    raw_hit = (s > 0).mean()
    raw_not_down = (s >= 0).mean()
    raw_worst = s.min()
    raw_best = s.max()
    avg_win = s[s>0].mean()
    avg_loss = s[s<=0].mean()
    
    # Q1 — with -2% stop
    capped = s.clip(lower=-0.02)
    stop_ret = capped.mean()
    stop_hit = (capped > 0).mean()
    stopped_count = (s < -0.02).sum()
    
    # Cumulative P&L
    cum_raw = (1 + s).prod() - 1
    cum_stop = (1 + capped).prod() - 1
    
    # Max drawdown
    cum_raw_series = (1 + s).cumprod()
    peak_raw = np.maximum.accumulate(cum_raw_series)
    dd_raw = ((cum_raw_series / peak_raw) - 1).min()
    
    cum_stop_series = (1 + capped).cumprod()
    peak_stop = np.maximum.accumulate(cum_stop_series)
    dd_stop = ((cum_stop_series / peak_stop) - 1).min()
    
    # Kelly
    w = s[s > 0]
    l = abs(s[s <= 0])
    if len(w) > 0 and len(l) > 0 and l.mean() > 0:
        kelly = raw_hit - ((1-raw_hit) / (w.mean() / l.mean()))
    else:
        kelly = float('nan')
    
    # Compare to full M3 (no filter)
    s_full = sig[horizon].dropna()
    raw_full_hit = (s_full > 0).mean()
    raw_full_ret = s_full.mean()
    capped_full = s_full.clip(lower=-0.02)
    stop_full_ret = capped_full.mean()
    dd_full = (( (1+s_full).cumprod() / np.maximum.accumulate((1+s_full).cumprod()) ) - 1).min()
    
    print(f"  Signals: {len(s)}")
    print(f"")
    print(f"  {'':<30s} {'Q1 Only':>12s} {'Full M3':>12s}")
    print(f"  {'-'*54}")
    print(f"  {'Hit rate':<30s} {raw_hit:>11.0%} {raw_full_hit:>11.0%}")
    print(f"  {'Not-down rate':<30s} {raw_not_down:>11.0%} {(s_full>=0).mean():>11.0%}")
    print(f"  {'Avg return (raw)':<30s} {raw_ret:>+11.2%} {raw_full_ret:>+11.2%}")
    print(f"  {'Avg return (-2% stop)':<30s} {stop_ret:>+11.2%} {stop_full_ret:>+11.2%}")
    print(f"  {'Avg win':<30s} {avg_win:>+11.2%} {s_full[s_full>0].mean():>+11.2%}")
    print(f"  {'Avg loss (raw)':<30s} {avg_loss:>11.2%} {s_full[s_full<=0].mean():>11.2%}")
    print(f"  {'Worst case':<30s} {raw_worst:>+11.2%} {s_full.min():>+11.2%}")
    print(f"  {'Stopped at -2%':<30s} {stopped_count:>11} {s_full[s_full<-0.02].sum():>11}")
    print(f"  {'Max drawdown (raw)':<30s} {dd_raw:>11.1%} {dd_full:>11.1%}")
    print(f"  {'Max drawdown (-2% stop)':<30s} {dd_stop:>11.1%} {'--':>12s}")
    print(f"  {'Cumulative return (raw)':<30s} {cum_raw:>+11.2%}")
    print(f"  {'Cumulative return (stop)':<30s} {cum_stop:>+11.2%}")
    print(f"  {'Kelly fraction':<30s} {kelly:>11.0%}")
    
    # Per-signal detail
    print(f"\n  All signals (chronological):")
    q1_sorted = q1.dropna(subset=[horizon]).sort_values('date')
    for _, r in q1_sorted.iterrows():
        ret = r[horizon]
        capped_ret = max(ret, -0.02)
        flag = ' << STOPPED' if ret < -0.02 else ''
        print(f"    {r['date'].date()} {r['ticker']:<6s} gap={r['gap']:5.1f}% ret={ret:+6.2%} stop_ret={capped_ret:+6.2%}{flag}")

print("\n" + "=" * 70)
print("SUMMARY: Q1-Only vs Full M3_p90_w90")
print("=" * 70)
print(f"\n  Q1-Only (gap < {gap_q1_threshold:.1f}%): ~{len(q1)} signals total")
print(f"  Full M3: ~{len(sig)} signals total")
print(f"\n  Trade-off: you give up {(len(sig)-len(q1))/len(sig):.0%} of signals for much better risk control.")
