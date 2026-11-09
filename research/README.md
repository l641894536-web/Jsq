# 研究脚本（交易台结论的出处）

在 Claude 工作区里跑的回测脚本，原样存档，方便复查和重跑。数据来自本仓库 `data` 分支（`market_data.load`），
脚本里的路径按工作区写死：`/home/claude/jsq`（本仓库）、`/home/claude/market-data`（data 分支）、`/home/claude/bt`（运行目录）。

| 脚本 | 做什么 |
|---|---|
| `contract_bt.py` | 合约短线规则模拟器：突破/均线交叉进场，前 L 根高低点止损，A=死拿、E=浮盈1R挪保本等出场，扣0.1%来回成本 |
| `regime.py`, `contract_regime.py` | 美股环境（纳指200日线 × VIX）；AMD/美光/戴尔 + 25只科技股分环境回测 |
| `gold_env.py` | 黄金白银：日线环境变量 + 小时线短线规则分牛熊 |
| `newsyms_bt.py` | 加密7币（比特币200日线）、23只非科技蓝筹（标普200日线） |
| `commod_bt.py` | 铂金、钯金、铜、天然气（Dukascopy 商品CFD，自身200日线） |
| `build_contract_stats.py` | 汇总成 gh-pages `env_static.json` 的 `contract_stats`（含前后两段 h1/h2） |
| `feat_bt.py` | 美股：能不能用开单前就知道的条件（波动、涨幅、强弱、自身战绩）挑出适合做突破的股票（结论：不能） |
| `daily_bt.py` | 美股日线突破（20日高低点进场、10日反向离场）对比随便进场，扣资金费（结论：没有普遍优势） |
| `structure_bt.py`, `structure_report.py` | K线结构（摆动高低点）转向：方向、幅度、顺着做到认错位的盈亏，多周期组合 |
| `analog_bt.py` | 历史相似行情（找最像的20段历史看之后怎么走），方向和波动范围检验（结论：没通过） |
| `bear.py` | 美股跌破200日线：长熊还是短恐慌，认错线 |
| `build_panel.py`, `sentiment.py`, `test_sent.py`, `build_env.py` | A股情绪温度（11个指标） |
| `ashare_vs_us.py`, `stock_bt.py`, `stock_split.py`, `stock_signals.py`, `trendstart.py` | 抄底、个股信号、趋势起点 |

页面怎么用这些统计：合约结论卡按 `breakout|E|环境|方向` 取统计，平均≥0.08R 且前后两段都≥0.03R = 稳定优势；
≥0.08R 但有一段不赚 = 时灵时不灵（轻仓）；−0.03～0.08R = 基本不赚；更低 = 亏；不足100笔 = 样本少。
