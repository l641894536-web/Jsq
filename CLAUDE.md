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
load.binance_spot("1h", "PAXGUSDT")            # spot gold token, 1h/15m back to 2020 (XAUUSDT perp only from 2025-12)
load.dukascopy(["XAUUSD", "XAGUSD"])           # interbank spot gold/silver 1h from 2020; cleaner than PAXG before 2025 (thin book, spiky wicks)
load.dukascopy("XAUUSD", interval="5m")        # 5-minute bars built from Dukascopy 1-minute files (complete months)
load.dukascopy(["XPTCMDUSD", "COPPERCMDUSD"])  # platinum / palladium / copper / natural gas CFDs 1h (GASCMDUSD, XPDCMDUSD); price checked vs PL=F/HG=F
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
- Dukascopy throttles GitHub runners (503 / timeouts); the 1h backlog of US stocks is still filling. New symbols in
  `DK_COMMOD_1H` are fetched first, and the stage gives up after 40 consecutive refused months.
- Check a run without auth: `curl -s https://api.github.com/repos/l641894536-web/Jsq/actions/runs?per_page=3`.
- The owner wants the workbench to be usable and kept up to date; research / strategy code may live
  in this repo (owner, 2026-11-08). Don't block useful changes on "the repo is public".

## Workbench (交易台, GitHub Pages)
- Branch `gh-pages`: `index.html` (live Binance charts + 市场环境 block), `env.json`, `env_static.json`
  (research conclusions shown on the page; edit by hand), `snapshot.json`.
- Contract card verdicts come from `env_static.json` `contract_stats` (built by `research/build_contract_stats.py`):
  key `breakout|E|bull/bear|long/short`, groups stock_main / stock_other / stock_nontech / crypto / commod / XAUUSD / XAGUSD.
- `env.json` is rebuilt by `.github/workflows/env-page.yml` after every successful `market-data` run,
  using `pages/env_pipeline.py` (A-share sentiment temperature + bull/bear, US 200-day lines / VIX /
  stop line, plus `live` baselines). The page then updates intraday on its own: A-share quotes from
  qt.gtimg.cn (`s_` format, 400 codes per request), US from Binance QQQUSDT / SPYUSDT perps.
- 首页"今天能做什么"清单和结论卡用同一个突破信号函数（`brk`，源码 `research/workbench_card.js`），和 `research/contract_bt.py` 出场F逐笔对账
  （`research/parity_check.py`）。只有回测有优势的才会显示"可以做"：黄金/白银（自身200日线上方做多）、7个主流币（比特币50日线上做多/下做空）、
  AMD/美光/戴尔（牛市突破做多、熊市回调企稳）。单只股票自己的成绩（`sym_*`）不当依据。成绩统一写成"100U开5倍每次赚亏多少U"（`contract_stats` 的 `u|环境|方向`）。
- market-data 续跑（机器人 workflow_dispatch）结束后不会触发 env-page 的 workflow_run，所以 market-data 最后一步显式触发 env-page。

