# Notes for Claude

This repo is the owner's market-data pipeline for backtests. The Claude cloud workspace cannot
reach market-data sites directly (egress policy blocks them), but it can reach GitHub, so a
GitHub Actions workflow fetches the data and commits it to branch `data`.

## Using the data in a backtest
```bash
git clone --depth 1 -b data https://github.com/l641894536-web/Jsq.git ~/market-data   # ~minutes, a few hundred MB
# refresh later:
git -C ~/market-data fetch --depth 1 origin data && git -C ~/market-data reset --hard FETCH_HEAD
```
```python
import sys; sys.path.insert(0, "/home/claude/jsq")
from market_data import load
load.status()                                   # what the last run did, newest dates per source
load.a_share(start="2024-01-01", adjust="hfq")  # raw / hfq / qfq; plus a_share_stocks(), a_share_index()
load.us_daily(["NVDA", "GC=F"]); load.us_hourly("GC=F")
load.binance("1h", "XAUUSDT"); load.binance("1d")  # 1d = every USD-M perp; 1h/15m = watchlist
```
Local pandas has no pyarrow, so storage is CSV + xz, monthly partitions (`<dataset>/YYYY/YYYY-MM.csv.xz`).

## Pipeline facts
- Workflow: `.github/workflows/market-data.yml`, daily 22:17 UTC; also runs on pushes to
  `market_data/**` (mode from `market_data/push_mode.txt`: `smoke` writes to `data/_smoke/`, `full` is real).
- `data` branch is force-pushed as one orphan commit each run (no history bloat).
- A-share backfill is time-budgeted; if unfinished the workflow re-dispatches itself (max 12 times).
- A-share bars are UNADJUSTED; `load.a_share(adjust=...)` builds the factor from the exchange
  pre-close (prod of close[t-1]/preclose[t]), so adjusted returns equal pctChg exactly (verified on
  3.4M rows). baostock's `adj_factor.csv.xz` is kept but has spurious records (sz.000001 2020-12-31).
- Stock perps are validated against the US share price (median ratio within 3%, corr >= 0);
  look-alike crypto tokens (C, F, O, MET...) and CLUSDT (crude oil) are rejected.
- Binance REST is geo-blocked from US runners, so klines come from the data.binance.vision archive
  (newest bar = yesterday UTC). Stock perps (e.g. TSLAUSDT) are auto-detected and get intraday bars.
- Check a run without auth: `curl -s https://api.github.com/repos/l641894536-web/Jsq/actions/runs?per_page=3`.
- Strategy / backtest code should NOT be committed here (the repo is public); keep it in the session.
