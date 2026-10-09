# Jsq · 行情数据自动库

GitHub Actions 每天北京时间 06:17 自动抓取行情，存到本仓库的 **`data` 分支**（只保留最新快照，仓库不会越来越大）。用来做回测，不用手动上传任何文件。

| 市场 | 来源 | 内容 | 起始 |
|---|---|---|---|
| A股 | baostock | 全部A股日线（含已退市，未复权）+ 复权因子 + 行业 + 主要指数 | 2015 |
| 美股 | Yahoo Finance | 标普500 + 纳斯达克100 + 常用ETF/指数 + 金银等期货，日线；部分品种1小时线 | 2010（小时线约近2年起） |
| 币安 | data.binance.vision | 全部U本位永续合约日线；BTC/ETH/黄金/白银/股票合约等 1小时、15分钟线 | 2017（15分钟 2022） |

- 抓取代码：`market_data/`，要抓的品种在 `market_data/config.py` 里改
- 每次运行的结果：`data` 分支的 `status.json` 和 `logs/last_run.log`
- 读取数据：`market_data/load.py`
