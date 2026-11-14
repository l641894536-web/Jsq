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
- 正股页（2026-11-13）"正股：现在买什么"（`research/workbench_picks.js`，内联在 index.html `<script id="picksjs">`）：美股名单读 gh-pages `stocks_us.json`
  （`pages/stocks_us.py`，env_pipeline 每天生成：营收+净利润同比都前30%、近半年不是最弱30%、离一年高点不到30%；跌太多的列"观察"并给回到线上的价格），
  A股观察名单读 `stocks_a.json`（新增字段 amt=近20日均成交亿、dd=离一年高点）。依据 research/us_entry_bt.py（直接买、单只不设均线止损）。
  "美股当晚 → 第二天A股"面板的数字写死在脚本里，来自 research/us_cn_link_bt.py（重跑后要手动改 LINK 常量）。
- 正股页"A股短线情绪：现在在哪一段"（2026-11-13，`research/workbench_cycle.js`，内联 `<script id="cyclejs">`）：阶段 = 情绪温度 + 和前5天平均比，
  env_pipeline 写进 `a.today.phase`（另有 zbl 炸板率、prem 涨停次日）；各阶段数字在 env_static.json 的 `gap_research`（env_pipeline 原样带进 env.json，
  由 research/build_gap_research.py 生成）。查个股（`research/workbench_stock_lookup.js`）加"开盘习惯"：stocks_a.json 新字段 gu_n/gu_f/gu_x、gd_n/gd_f/gd_x
  （近250天高开/低开2~7%之后）、vq（波动五分位）、ztk（最后一天连板数）；盘中从 qt.gtimg.cn 取单只完整行情（f[3]现价 f[4]前收 f[5]开盘）对照今天的开盘。
- A股小市值轮动（2026-11-14，research/ashare_factor_bt.py → ashare_small_bt.py）：日均成交≥3000万、非ST、上市满250天里总市值最小30只，每月第一个交易日换。
  stocks_a.json 新字段 cap（总市值亿，最近一期财报总股本×收盘）、sm（市值排名1..60），顶层 small.cut30。正股页"A股"段落显示名单和选股方法体检（FAC 常量写死在 workbench_picks.js）。
  `pages/stock_ledger.py`（env-page 里 ledger 之后跑）每月第一次出数据时记一篮（A股小市值30、美股成长名单），写 gh-pages `stock_ledger.json`，验证页"正股名单记账"显示。
- A股交易做法体检（2026-11-14，research/ashare_trader_bt.py：打板/接力/回马枪/回踩/超跌/断层/二八/行业轮动/隔夜/节前）；结果常量 TRD/TRD2 写死在 workbench_picks.js。
  小市值"刹车"（research/ashare_brake_small.py）：全A等权跌破20日线清仓；env_pipeline 写 `a.today.ew_vs_ma20`、`live.a.ew_sum19`，页面 JSQ_LIVE_A.ew_vs20 盘中估算。
- A股5分钟线（2026-11-14）：`market_data/a_share_min.py`（baostock，6进程，config.A_MIN_CODES = 用户持仓 沪电/工业富联/国泰半导体ETF + 同类科技股，2021起），
  存 data 分支 `a_share/min5/`，`load.a_share_min()`；push 到 market_data/** 时只跑 `market_data/push_only.txt` 里的阶段（现在是 a_share_min），定时任务照常全跑。
  研究 research/ashare_intraday_t.py / _t2.py；正股页"我的科技股"（`research/workbench_tech.js`，内联 `<script id="techjs">`）盘中用腾讯分时
  （web.ifzq.gtimg.cn/appstock/app/minute/query?_var=…，没在沙盒里实测过，取不到就只用 qt.gtimg.cn 报价）提示高开等9:45、低开开盘附近做T。
- 被套了怎么办（2026-11-14，research/holder_bt.py / holder3_bt.py / holder_entry_bt.py，"离一年高点跌30%"后250天）：正股页最上面"我的正股"
  （`research/workbench_hold.js`，内联 `<script id="holdjs">`，持仓存 localStorage `jsq.mystk` = [{c,cost,u份数}]）。规则：反弹不卖（死扛比反弹卖一半多5~6个点）；
  只在大盘在200日线下（A股全A等权、美股纳指100）且个股60天没比大盘多跌20%时，按一年高点×0.63/×0.56各加1份，最多3份；否则上限1份，超过的在第一波反弹（这轮低点×1.15）卖掉。
  数据：stocks_a.json 新字段 px/m60/v200、顶层 mkt60、`etf` 块（A_MIN_CODES 里的ETF，用5分钟线拼日收盘，拆分按整数比例折算）；stocks_us.json 的 `hold` 块（美股范围约570只 + qqq60）。
  env-page 的 data 稀疏检出加了 /a_share/min5。页面里的回测数字写死在 workbench_hold.js 的 ST 常量。
- 美国大数据日研究 research/event_bt.py（CPI/非农/议息日期写死在脚本里，来自美联储和 BLS 官网存档）：结论在 env_static findings，页面"本周大事"提醒还没做。
- 模拟仓（今天页 `renderPaper`，2026-11-13）：以 ledger.json 为准，页面用实时小时线把没平的单子往前推（`sigEngine` 的 trace 带出场价/原因），
  记账数据之后新出的信号先记成"今天的"；和 ledger.py 逐笔对过（同一时间、同一原因、U 差 <0.6）。ledger.json 另有 `replay30`（最近30天回放，不算验证）。
  验证页"模拟仓按规则看"（`renderPaperRules`）拿已平单和这条规则5年回测平均比。我的持仓每笔下面有止损拉杆（`initStopBars`），拖动/输入实时分析，松手才存。
