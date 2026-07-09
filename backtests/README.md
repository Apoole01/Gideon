# Backtests

## V1 — Initial Accumulation Models (July 8, 2026)
- 6 models tested against 61 tickers, 57 trading days
- Flat spot filter (<2%) found to destroy alpha
- M3 (elastic band) identified as most promising
- Backwardation confirmed as quality overlay

## V2 — Enhanced Backtest (July 9, 2026)
- **5 changes:** not-spiked filter (<5%), M3 grid search, BW magnitude tiers, earnings exclusion, put VWKS
- **Winner:** M3_p90_w90 — 67% hit rate, elastic band at 90th percentile / 90-day window

## Risk-Managed Strategy (July 9, 2026)
- M3_p90_w90 + Q1 gap filter (<6.3%) + -2% stop loss + t7 exit
- **83% hit rate, -4% max drawdown, worst trade -2%**
- ~1-2 actionable signals per week across 61 tickers

## Data Source
All backtests use the S3 enriched chain (`dashboard_data/enriched_chain_gold.parquet`) and yfinance for forward returns. CSV output files excluded from git due to size — regenerate by running the scripts.

## Running
```bash
# Requires: boto3, pyarrow, pandas, numpy, yfinance, lxml
pip install boto3 pyarrow pandas numpy yfinance lxml
python backtests/v2/backtest_v2.py
```
