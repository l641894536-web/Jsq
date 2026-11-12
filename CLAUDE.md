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
load.binance_funding(["BTCUSDT"])                # funding-rate settlements 2020→ (finished months), 7 coins + XAU/XAG + AMD/MU/DELL/NVDA/TSLA/SPCX
load.binance_metrics("BTCUSDT")                   # hourly open interest, long/short ratios, taker buy/sell ratio, 7 main coins from 2021-12
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
  （`research/parity_check.py`）。只有回测有优势的才会显示"可以做"：黄金/白银（自身50日线上方做多，2026-11-11 起由200日线改为50日线，research/metals50_stats.py）、7个主流币（比特币50日线上做多/下做空）、
  AMD/美光/戴尔（牛市突破做多、熊市回调企稳）。币和AMD/美光/戴尔牛市突破的结论卡给"赚了再加"价位（3成→1R加3成→2R加4成，research/pyramid_bt.py），金银和回调企稳一次性开。单只股票自己的成绩（`sym_*`）不当依据。成绩统一写成"100U开5倍每次赚亏多少U"（`contract_stats` 的 `u|环境|方向`）。
- market-data 续跑（机器人 workflow_dispatch）结束后不会触发 env-page 的 workflow_run，所以 market-data 最后一步显式触发 env-page。
- 界面（2026-11-11 起）是白底"仪器面板"风格，参照用户发的视频。数据图脚本源码 `research/workbench_viz.js`（内联在 index.html 的 `<script id="vizjs">`）：
  规则小球板读 gh-pages 的 `balls.json`（现行规则近5年每一笔的U，由 research/risk_bt.py 的 risk_trades 导出；规则改了要重新导出），
  价格山脊图用币安日线最近20天波动 + 卡片的规则止损（`JSQ_PLAN()`）或"我已经有仓位"里填的止损。字体自带在 gh-pages `fonts/`（Doto 点阵、JetBrains Mono），不要再引 Google Fonts（国内打不开）。
- 首页"我的持仓"可以连币安只读 API（用户自己建 key，只勾"允许读取"）：密钥只存手机 localStorage（`jsq.bnkey`），
  经币安 WebSocket API `wss://ws-fapi.binance.com/ws-fapi/v1` 的 `v2/account.position` / `v2/account.status` 读（REST 不允许网页跨域带
  X-MBX-APIKEY）。每分钟同步，覆盖 `jsq.pos.*`（src=bn），止损读不到、沿用手填；本金填合约账户 totalMarginBalance。Claude 不经手密钥。
- 页面结构（2026-11-12 重排）：一行页头 + 底部四个入口 今天/品种/正股/验证（`#tabs` 是 `.dock`，`setTab` 在 card.js，默认"今天"）。
  今天页 = 现在要做的（`renderTodo`：持仓要动的 + 可以做的信号）、我的持仓（持仓尺 `railHTML`、仓位格子）、离信号多远（跑道 `sigLane`）、大环境（跑道 `renderEnvLanes`）。
  品种页 = 原来的结论卡/山脊图/小球板/K线；放量跳空清单在正股页。验证页 = 规则体检（含"最近半年变差"自动警报）、模拟账户（balls.json 按月打乱重排500次）、
  每半年成绩热力图、自动记账 vs 回测预期带子、影子规则（ledger.py 的 `shadow`：没采用/换下来的做法同时记账）、进化日志（gh-pages `evolution.json`，手工维护）。
- 模拟仓（今天页 `renderPaper`，2026-11-13）：以 ledger.json 为准，页面用实时小时线把没平的单子往前推（`sigEngine` 的 trace 带出场价/原因），
  记账数据之后新出的信号先记成"今天的"；和 ledger.py 逐笔对过（同一时间、同一原因、U 差 <0.6）。ledger.json 另有 `replay30`（最近30天回放，不算验证）。
  验证页"模拟仓按规则看"（`renderPaperRules`）拿已平单和这条规则5年回测平均比。我的持仓每笔下面有止损拉杆（`initStopBars`），拖动/输入实时分析，松手才存。
