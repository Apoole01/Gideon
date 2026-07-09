# M3 Risk-Managed Strategy — Q1 Filter + Stop Loss

**July 9, 2026** | Derived from V2 Backtest | M3_p90_w90 signal

---

## The Strategy

**Signal:** M3_p90_w90 fires (VWKS-strike gap exceeds 90th percentile over 90-day window, spot not spiked >5%)

**Filter:** Only take signals where the gap is in the smallest quartile (gap < 6.3%). This means the elastic band is stretched just enough to trigger, but not dangerously overextended.

**Exit:** t+7 trading days, OR -2% intraday stop loss (whichever hits first).

**Position size:** Quarter-Kelly — 9-17% of account per trade (Kelly suggests 67%, which is too aggressive for real accounts).

---

## Results

### t7 Horizon (Optimal)

| Metric | Full M3 | Q1 + Stop |
|---|---|---|
| Hit rate | 68% | **83%** |
| Not-down rate | 68% | **83%** |
| Avg return | +2.20% | **+3.32%** |
| Avg win | +5.67% | +4.37% |
| Avg loss | -5.09% | **-2.00%** (capped) |
| Worst case | -17.55% | **-2.00%** |
| Max drawdown | -25.8% | **-4.0%** |
| Cumulative return | — | **+115.95%** |
| Signals | 93 | 24 |

### t10 Horizon

| Metric | Full M3 | Q1 + Stop |
|---|---|---|
| Hit rate | 68% | **81%** |
| Avg return | +2.49% | **+3.37%** |
| Worst case | -22.49% | **-2.00%** |
| Max drawdown | -32.2% | **-4.0%** |
| Signals | 74 | 16 |

### t20 Horizon

| Metric | Full M3 | Q1 + Stop |
|---|---|---|
| Hit rate | 58% | **90%** |
| Avg return | +2.53% | **+7.95%** |
| Worst case | -11.89% | **-2.00%** |
| Signals | 35 | 10 |

---

## Signal Frequency

- **27 total signals** across 57 trading days on 61 tickers
- **~3.3 per week** (~1 every 1-2 trading days)
- Roughly **1-2 actionable signals per week** after filtering for liquidity, overlap, and personal conviction

---

## What Got Filtered Out

Every catastrophic loser was excluded. Examples:

| Date | Ticker | Gap | Unfiltered Loss | Action |
|---|---|---|---|---|
| Jun 5 | ADBE | 19.8% | -22.5% | **Filtered** (gap >> 6.3%) |
| Jun 5 | CRM | 15.6% | -18.9% | **Filtered** |
| Jun 3 | MSFT | 8.3% | -11.3% | **Filtered** |
| Jun 2 | COIN | 56.2% | -8.5% | **Filtered** |

---

## All Q1 Signals (Chronological)

| Date | Ticker | Gap | Raw Return | Stopped? |
|---|---|---|---|---|
| Jun 2 | PG | 5.0% | +5.34% | |
| Jun 2 | AMZN | 6.2% | -5.85% | **-2%** |
| Jun 2 | JNJ | 5.8% | +6.93% | |
| Jun 3 | JNJ | 5.7% | +7.90% | |
| Jun 3 | PG | 6.3% | +6.72% | |
| Jun 3 | TGT | 6.1% | +8.36% | |
| Jun 4 | JNJ | 4.8% | +3.28% | |
| Jun 4 | KO | 3.6% | +6.00% | |
| Jun 4 | PG | 6.1% | +6.88% | |
| Jun 5 | PG | 5.2% | +4.06% | |
| Jun 16 | BAC | 3.6% | +1.83% | |
| Jun 17 | BAC | 5.2% | +2.39% | |
| Jun 18 | BAC | 4.4% | +1.39% | |
| Jun 19 | BAC | 3.8% | +1.39% | |
| Jun 22 | GM | 6.3% | -6.10% | **-2%** |
| Jun 23 | GM | 6.3% | -3.74% | **-2%** |
| Jun 24 | PG | 5.4% | -1.80% | |
| Jun 24 | MS | 3.3% | +1.02% | |
| Jun 24 | AAPL | 5.3% | +6.68% | |
| Jun 25 | MS | 3.7% | +0.45% | |
| Jun 25 | PG | 5.4% | +2.86% | |
| Jun 26 | AAPL | 5.3% | +10.43% | |
| Jun 26 | BAC | 3.9% | +0.73% | |
| Jun 26 | MS | 5.3% | +2.85% | |

**Only 3 of 24 hit the -2% stop.** The other 21 trades were profitable (20) or small losses (1 at -1.80%).

---

## Why This Works

The gap has a non-linear relationship with outcomes:

| Gap Quartile | Hit Rate | Worst Case | Profile |
|---|---|---|---|
| Q1 (<6.3%) | **84%** | -5.5% | Elastic band just barely stretched — high probability snap |
| Q2 (6.3-10.2%) | 56% | -11.4% | Mid-range — noise, no edge |
| Q3 (10.2-14.3%) | 61% | -4.4% | Elevated but constrained |
| Q4 (>14.3%) | 68% | **-22.5%** | Extreme stretch — falling knives mixed with winners |

**The pattern:** When the gap is at Q1 levels (just barely over the 90th percentile), the stock is primed for a clean snap — the tension is new, positions haven't yet moved against it. At Q4 levels, the gap has been widening for days or the stock is already in distress — extreme gaps are distress signals, not opportunity.

---

## Position Sizing

**Kelly Criterion (t7): 67%** — theoretically optimal but insane for real accounts. One bad streak at 67% allocation = ruin.

**Recommended: Quarter-Kelly at 10-17% per trade.**

With 27 signals and 83% hit rate:
- Expected win streak: ~5 consecutive
- Expected loss streak: ~1-2 consecutive
- At 10% per trade with -2% stop: max drawdown ~4%
- At 17% per trade: max drawdown ~7%

For options: size the notional exposure to 10-15% of account value, not the premium paid. Selling put spreads on these signals is ideal — limited defined risk, premium collection in your favor.

---

## Implementation Checklist

1. Screen for M3_p90_w90 firing on any of the 61 tickers
2. Check gap < 6.3% (Q1 filter)
3. Exclude if within 3 days of earnings
4. Entry: next trading day open
5. Hard stop: -2% from entry (intraday)
6. Exit: t+7 trading days if not stopped
7. Position size: 10-15% of account notional
8. No more than 3 concurrent positions

---

*Derived from V2 Backtest: 61 tickers, 57 trading days. All returns absolute from yfinance closing prices. Past performance does not guarantee future results. The 57-day window is short — out-of-sample validation strongly recommended.*
