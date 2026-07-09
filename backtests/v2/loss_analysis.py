"""Loss analysis — M3_p90_w90 signals: winners vs losers"""
import pandas as pd, numpy as np

feat = pd.read_csv(r'C:\Users\GideonAdmin\.openclaw\workspace\accumulation_features_v2.csv', parse_dates=['date'])

sig_col = 'sig_M3_p90_w90'
sig = feat[feat[sig_col] == True].copy()
# Exclude near-earnings
sig = sig[sig['near_earnings'] == False]

print("=" * 70)
print("M3_P90_W90 — WINNER vs LOSER ANALYSIS")
print("=" * 70)

for horizon, label in [('fwd_t5','t5'), ('fwd_t7','t7'), ('fwd_t10','t10'), ('fwd_t20','t20')]:
    print(f"\n{'='*70}")
    print(f"HORIZON: {label}")
    print(f"{'='*70}")
    
    s = sig[horizon].dropna()
    if len(s) == 0: continue
    
    winners = sig[sig[horizon] > 0]
    losers = sig[sig[horizon] <= 0]
    
    print(f"\nWinners: {len(winners)} ({len(winners)/len(s)*100:.0f}%)")
    print(f"  Avg return: {winners[horizon].mean():+.2%}")
    print(f"  Best: {winners[horizon].max():+.2%}  Worst: {winners[horizon].min():+.2%}")
    print(f"  Median: {winners[horizon].median():+.2%}")
    print(f"  > +5%: {(winners[horizon] > 0.05).sum()} ({(winners[horizon] > 0.05).mean():.0%})")
    
    print(f"\nLosers: {len(losers)} ({len(losers)/len(s)*100:.0f}%)")
    print(f"  Avg return: {losers[horizon].mean():+.2%}")
    print(f"  Worst: {losers[horizon].min():+.2%}")
    print(f"  Median: {losers[horizon].median():+.2%}")
    print(f"  Worse than -5%: {(losers[horizon] < -0.05).sum()} ({(losers[horizon] < -0.05).mean():.0f})")
    
    # Win/Loss ratio by magnitude
    avg_win = winners[horizon].mean()
    avg_loss = abs(losers[horizon].mean())
    print(f"\n  Avg Win: {avg_win:+.2%} | Avg Loss: {avg_loss:.2%} | Ratio: {avg_win/avg_loss:.2f}x" if avg_loss > 0 else "")
    
    # Distribution buckets
    print(f"\n  Return distribution:")
    buckets = [(-1.0, -0.10), (-0.10, -0.05), (-0.05, -0.02), (-0.02, 0), 
               (0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 1.0)]
    for lo, hi in buckets:
        n = ((s >= lo) & (s < hi)).sum()
        bar = '#' * max(1, int(n / max(1, len(s)) * 40))
        print(f"  {lo:+.0%} to {hi:+.0%}: {n:>3d} ({n/len(s)*100:>4.1f}%) {bar}")

# --- CHARACTERISTICS OF LOSERS ---
print(f"\n{'='*70}")
print("LOSER CHARACTERISTICS — What's different when M3 fails?")
print(f"{'='*70}")

s10 = sig['fwd_t10'].dropna()
w10 = sig[sig['fwd_t10'] > 0]
l10 = sig[sig['fwd_t10'] <= 0]

features_to_check = ['gap', 'spot_chg_5d', 'skew_3d', 'vwks_3d', 'vwks_put_3d', 
                     'notional_delta', 'nd_3d', 'bw_magnitude', 'iv_fm', 'iv_bm']

print(f"\n{'Feature':<22s} {'Winners':>10s} {'Losers':>10s} {'Diff':>10s} {'Direction'}")
print("-" * 65)
for f in features_to_check:
    if f in sig.columns:
        w_val = w10[f].dropna().mean()
        l_val = l10[f].dropna().mean()
        diff = w_val - l_val
        direction = 'Higher=Good' if diff > 0 else 'Lower=Good' if diff < 0 else 'Neutral'
        print(f"{f:<22s} {w_val:>10.4f} {l_val:>10.4f} {diff:>+10.4f} {direction}")

# --- CHECK SIGNAL STRENGTH ---
print(f"\n{'='*70}")
print("SIGNAL STRENGTH — Does gap magnitude predict outcome?")
print(f"{'='*70}")

sig_valid = sig.dropna(subset=['fwd_t10']).copy()
sig_valid['gap_quartile'] = pd.qcut(sig_valid['gap'], 4, labels=['Q1 (small)', 'Q2', 'Q3', 'Q4 (large)'])
for q in ['Q1 (small)', 'Q2', 'Q3', 'Q4 (large)']:
    sub = sig_valid[sig_valid['gap_quartile'] == q]
    hit = (sub['fwd_t10'] > 0).mean()
    ret = sub['fwd_t10'].mean()
    worst = sub['fwd_t10'].min()
    print(f"  {q}: hit={hit:.0%} return={ret:+.2%} worst={worst:+.2%} n={len(sub)}")

# --- STOP LOSS SIMULATION ---
print(f"\n{'='*70}")
print("STOP LOSS ANALYSIS — If we cut losers at various thresholds")
print(f"{'='*70}")

for horizon, label in [('fwd_t5','t5'), ('fwd_t7','t7'), ('fwd_t10','t10')]:
    print(f"\n--- {label} horizon ---")
    s = sig[horizon].dropna()
    raw_ret = s.mean()
    raw_hit = (s > 0).mean()
    print(f"  No stop: ret={raw_ret:+.2%} hit={raw_hit:.0%}")
    
    for sl in [-0.02, -0.03, -0.05, -0.07, -0.10]:
        capped = s.clip(lower=sl)
        new_ret = capped.mean()
        new_hit = (capped > 0).mean()
        stopped = (s < sl).sum()
        not_stopped_avg = s[s >= sl].mean()
        print(f"  Stop at {sl:+.0%}: ret={new_ret:+.2%} hit={new_hit:.0%} avg_win={not_stopped_avg:+.2%} stopped={stopped}/{len(s)}")

# --- KELLY & POSITION SIZING ---
print(f"\n{'='*70}")
print("POSITION SIZING — Kelly Criterion")
print(f"{'='*70}")

for horizon, label in [('fwd_t7','t7'), ('fwd_t10','t10')]:
    s = sig[horizon].dropna()
    w = s[s > 0]
    l = s[s <= 0]
    
    if len(w) > 0 and len(l) > 0:
        win_prob = len(w) / len(s)
        loss_prob = len(l) / len(s)
        avg_win = w.mean()
        avg_loss = abs(l.mean())
        
        # Kelly fraction
        if avg_loss > 0:
            kelly = win_prob - (loss_prob / (avg_win / avg_loss))
            half_kelly = kelly / 2
            quarter_kelly = kelly / 4
        else:
            kelly = half_kelly = quarter_kelly = float('inf')
        
        print(f"\n  {label}:")
        print(f"    Win prob: {win_prob:.0%}  Loss prob: {loss_prob:.0%}")
        print(f"    Avg win: {avg_win:+.2%}  Avg loss: {avg_loss:.2%}")
        print(f"    Kelly: {kelly:.1%}  Half-Kelly: {half_kelly:.1%}  Quarter-Kelly: {quarter_kelly:.1%}")

# --- WORST CASE SCENARIOS ---
print(f"\n{'='*70}")
print("TAIL RISK — Worst losses on record")
print(f"{'='*70}")

for horizon, label in [('fwd_t7','t7'), ('fwd_t10','t10'), ('fwd_t20','t20')]:
    s = sig[horizon].dropna()
    worst = s.nsmallest(10)
    print(f"\n  {label} — 10 worst outcomes:")
    for idx in worst.index:
        row = sig.loc[idx]
        print(f"    {row['date'].date()} {row['ticker']:<6s}: {s[idx]:+.2%}  gap={row['gap']:.1f}%  spot_chg5d={row['spot_chg_5d']:+.2%}  bw_mag={row['bw_magnitude']:.3f}")

# --- MAX DRAWDOWN PATH ---
print(f"\n{'='*70}")
print("DRAWDOWN ANALYSIS — Sequential signal returns")
print(f"{'='*70}")

for horizon, label in [('fwd_t7','t7'), ('fwd_t10','t10')]:
    s = sig[horizon].dropna().sort_values('date')
    rets = s.values
    cum = (1 + rets).cumprod()
    peak = np.maximum.accumulate(cum)
    dd = (cum / peak) - 1
    
    max_dd = dd.min()
    max_dd_idx = dd.argmin()
    print(f"\n  {label}:")
    print(f"    Max drawdown: {max_dd:.2%}")
    print(f"    Avg consecutive loss streak: ...")

    # Consecutive losses
    consec = 0
    max_consec = 0
    consec_losses = []
    current_streak = []
    for r in rets:
        if r <= 0:
            consec += 1
            current_streak.append(r)
        else:
            if consec > max_consec:
                max_consec = consec
                consec_losses = current_streak.copy()
            consec = 0
            current_streak = []
    if consec > max_consec:
        max_consec = consec
        consec_losses = current_streak.copy()
    
    cumul_streak_loss = (1 + np.array(consec_losses)).prod() - 1 if consec_losses else 0
    print(f"    Max consecutive losses: {max_consec}")
    print(f"    Worst streak P&L: {cumul_streak_loss:+.2%}")

print("\n" + "=" * 70)
print("ANALYSIS COMPLETE")
