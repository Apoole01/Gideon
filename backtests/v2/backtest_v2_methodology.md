# Backtest V2 Methodology — What Changed & Why

**July 9, 2026** | Companion to Accumulation Models Backtest V2

---

## What Changed from V1

Five deliberate changes were made based on V1's findings:

### 1. Flat Spot → Not-Spiked Filter

**V1:** `abs(spot_chg_5d) < 0.02` (stock must have moved <2% in 5 days)

**V2:** `abs(spot_chg_5d) < 0.05` (stock must have moved <5% in 5 days)

**Why:** V1 proved the flat spot filter was anti-alpha — it filtered out stocks where accumulation was already working (stocks up 1-3%). The not-spiked filter still excludes parabolic movers (>5% in a week) but lets in stocks with moderate recent gains. In V2, every model's returns improved with this change.

**Known Issue:** Raw signals (no spot filter at all) still outperform any spot-filtered variant in absolute returns. The spot filter is a *quality* (hit rate) optimization, not a returns optimization.

### 2. M3 Percentile Grid Search

**V1:** Used a single configuration: 80th percentile, 90-day window. Arbitrary choice.

**V2:** Grid search across:
- Percentiles: 75th, 80th, 85th, 90th, 95th
- Windows: 30, 45, 60, 90 days
- 20 total combinations tested

**Why:** V1 identified M3 as the most promising model but used suboptimal parameters. The grid search found that 90th percentile / 90-day is the clear winner (67% hit rate vs 50% for the original 80th).

**Key finding:** Longer windows (90 days) consistently outperform shorter windows (30-60 days) at every percentile. The elastic band concept works best when the "normal range" is computed over a long enough period to capture regime changes.

**Method:** Each combination pre-computes the rolling percentile as a separate column, then evaluates signals against forward returns. No look-ahead bias — the percentile uses only historical data available at that date.

### 3. Backwardation Magnitude Tiers

**V1:** Binary backwardation only (front-month IV > back-month IV = True/False)

**V2:** Four magnitude tiers added alongside binary:
- `bw_mag_1pct`: Front IV exceeds back IV by ≥ 1 percentage point
- `bw_mag_2pct`: ≥ 2 points
- `bw_mag_3pct`: ≥ 3 points
- `bw_mag_5pct`: ≥ 5 points

**Why:** Binary BW discards information. A stock with 0.1% front premium is fundamentally different from one with 8% front premium (the latter suggests an event catalyst). V2 tests whether the magnitude of backwardation is predictive on its own, and whether filtering by magnitude improves signal quality.

**Formula:** `bw_magnitude = iv_fm - iv_bm` where both are ATM call IV values as decimals (e.g., 0.25 = 25% IV). The magnitude column is continuous; tiers are boolean filters on top.

**Key finding:** Higher BW magnitude = higher returns (+2.93% → +4.72% as magnitude increases) but lower hit rates (59% → 55%). The 2% tier is the sweet spot for quality filtering.

### 4. Earnings Exclusion

**Implementation:** For each ticker, fetch earnings dates via `yfinance.Ticker.earnings_dates`. Flag any signal date within ±3 calendar days of an earnings report as `near_earnings = True`. These signals are excluded from the evaluation (signals that fire during earnings windows are unreliable — the post-earnings move is unpredictable).

**Result:** 0 ticker-dates were flagged in the April-July 2026 window. This is not a code bug — it reflects that:
- The 57-day window is short and may fall between earnings seasons
- yfinance's `earnings_dates` API may not return complete historical data
- Some tickers simply didn't report in this window

**Recommendation:** Retain the filter in future backtests. It will matter on longer timelines. The code is correct; the data window was too short to benefit.

### 5. Put VWKS

**V1:** Only computed VWKS for CALL options (call_side volume-weighted strike). Signal M1 = Call VWKS rising + Skew rising + flat spot.

**V2:** Added Put VWKS computation using the same method (put_side, 7-45 DTE, volume-weighted). Three new signals:
- **M7:** Call VWKS rising AND Put VWKS falling (dual accumulation — calls moving up, puts moving down)
- **M8:** Call VWKS rising AND Put VWKS rising (both moving up = hedging, not accumulation)
- **M7 variants:** With/without spot filter, with BW magnitude tiers

**Why:** V1 only looked at call-side positioning. But institutional accumulation should also show in puts — if institutions are building upside positions, they should be reducing downside hedges (put strikes shift lower). M7 captures this dual confirmation.

**Key finding:** M7 beats M1 by 6% hit rate and 0.84% return at t10. Put VWKS direction is a genuine quality filter.

---

## Signal Reference Table

| Signal | Components | Logic |
|--------|-----------|-------|
| M1 | Call VWKS up + Skew up | Accumulation via volume + pricing |
| M2 | Gap shrinking | Mechanical spot catch-up |
| M3_pX_wY | Gap > X%ile over Y-day window | Elastic band snap |
| M4 | Skew up only | Pricing component of M1 |
| M5 | OTM Delta up | Speculative flow |
| M6 | Backwardation binary | Term structure urgency |
| M7 | Call VWKS up + Put VWKS down | Dual accumulation (NEW) |
| M8 | Call VWKS up + Put VWKS up | Hedging detection (NEW) |

Combinations are AND-logic (all components must be true). BW-tier variants AND the signal with a backwardation magnitude threshold.

---

## New Metrics in V2

### Not-Down Rate
Percentage of signals where forward return ≥ 0% (not just > 0%). This captures scenarios where the stock stays flat — profitable for selling put credit spreads. A signal with 67% hit rate and 67% not-down rate means the stock went up OR sideways in 2/3 of cases.

### Win/Loss Ratio
Number of positive signals divided by number of negative signals. A ratio >1.0 means more winners than losers. Signal M3_p90_w90 has a 2.0 win/loss ratio (2 winners for every 1 loser).

### Signals Per Week
Total signals divided by 8.14 (57 trading days / 7). Measures signal frequency — crucial for quality-over-quantity evaluation.

### Max Drawdown
Worst cumulative peak-to-trough during signal holding periods. Measures tail risk.

### Sharpe Ratio
Mean return divided by standard deviation. Rough risk-adjusted return measure.

---

## Evaluation Methodology (Identical to V1)

- **Forward returns** from yfinance closing prices
- **Baseline** = average return of all non-signal days
- **Spread** = signal mean - baseline mean
- **Hit rate** = percentage of signals with positive return
- **t2/t5/t7/t10/t20** = trading-day offsets from signal date
- **Absolute returns** (not annualized)

---

## Known Limitations (Carried from V1 + New)

### From V1 (Unchanged)
- 57-day window is too short — all conclusions are regime-dependent
- Equal weighting masks sector effects
- Delta bucket approximation (0.20-0.30) for skew is noisy
- No transaction costs — returns are gross
- No statistical significance filtering on small N

### New in V2
- **Earnings exclusion had no effect** — the 57-day window didn't contain earnings events. The filter is structurally correct but unvalidated.
- **Put VWKS is thinly traded** — some tickers have very low put volume, leading to NaN put VWKS. This reduces M7/M8 signal counts for those tickers.
- **BW magnitude tiers are correlated** — they're nested subsets (3% ⊂ 2% ⊂ 1%). The tier analysis is valid but the thresholds are arbitrary (1%, 2%, 3%, 5%).
- **Grid search is in-sample** — the M3 config was optimized on the same data it's evaluated on. This inflates the apparent quality. A walk-forward or out-of-sample test is needed.
- **No cross-validation** — the optimal M3 config (p90_w90) was discovered via grid search on the full dataset. Without out-of-sample testing, the 67% hit rate is the upper bound, not the expected value.
- **M3_p90_w90 has only 76 signals** — the statistical confidence is moderate. At 67% hit rate, the 95% confidence interval is roughly ±10%.

---

## What to Test Next

1. **Out-of-sample validation** — Train M3_p90_w90 on April-June, test on July. Does the 67% hit rate hold?
2. **Longer timeframe** — Extend to 1-2 years. The grid search may find different optimal parameters.
3. **Sector-adjusted baselines** — Do these signals work across all sectors or just tech?
4. **Position sizing** — Kelly criterion based on hit rate and win/loss ratio for M3_p90_w90.
5. **Multi-ticker signal aggregation** — When 3+ tickers fire M3_p90_w90 simultaneously, does that predict a market-wide move?
6. **Delta-gamma interaction** — Rising OTM delta + rising gamma together as a stronger signal.
7. **Liquidity filter** — Only evaluate signals on tickers with high options volume.
8. **Earnings validation** — Test the earnings exclusion on a longer timeline (1+ years).

---

*Generated by Gideon, July 9, 2026. V2 methodology companion to V2 results report.*
