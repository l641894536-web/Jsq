"""What to fetch. Edit the lists here; the next run picks the changes up."""

# ------------------------------------------------------------------ A-shares (baostock)
A_START = "2005-01-01"   # moved from 2015: older history is backfilled automatically (see a_share.plan_tasks)
A_INDICES = {
    "sh.000001": "上证指数",
    "sz.399001": "深证成指",
    "sh.000016": "上证50",
    "sh.000300": "沪深300",
    "sh.000905": "中证500",
    "sh.000852": "中证1000",
    "sz.399006": "创业板指",
    "sh.000688": "科创50",
}
A_SMOKE_CODES = ["sh.600519", "sz.000001", "sh.688981", "sz.300750", "sz.002415",
                 "sh.600570", "sz.300059", "sh.601138", "sz.000725", "sh.603501"]

# ------------------------------------------------------------------ US (yfinance)
US_START = "2010-01-01"
US_ETFS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "IEF", "HYG", "GLD", "SLV", "GDX", "GDXJ",
           "USO", "UUP", "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "ARKK", "TQQQ", "SQQQ",
           "SOXL", "KWEB", "FXI", "EEM", "IBIT", "ETHA"]
US_INDICES = ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "^TNX", "DX-Y.NYB"]
US_FUTURES = ["GC=F", "SI=F", "HG=F", "PL=F", "CL=F", "ES=F", "NQ=F"]
US_EXTRA_STOCKS = ["MSTR", "COIN", "HOOD", "CRCL", "TSM", "ASML", "BABA", "PDD", "JD", "BIDU",
                   "NIO", "LI", "XPEV", "BILI", "FUTU", "SMCI", "ARM", "MARA", "RIOT", "CLSK",
                   "CRWV", "SNOW", "SHOP", "RDDT", "NET", "SOFI", "RKLB", "IONQ", "OKLO",
                   "GME", "AMC", "SPOT", "SE", "MELI", "NU", "UBER", "ABNB",
                   # Nasdaq-100 members not in the S&P 500
                   "AZN", "CCEP", "TEAM", "GFS", "ZS", "MDB", "MRVL", "TRI"]
# Long daily history (back to 1985 or listing) for indices, index ETFs, metals and a few stocks,
# so environment research covers 2000-02 and 2008. Everything else starts at US_START.
US_LONG_START = "1985-01-01"
US_LONG_TICKERS = ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "^TNX", "DX-Y.NYB",
                   "SPY", "QQQ", "DIA", "IWM", "TLT", "IEF", "GLD", "SLV", "SMH", "SOXX",
                   "XLK", "XLF", "XLE", "XLV", "GC=F", "SI=F", "HG=F", "CL=F", "AMD", "MU"]
US_LONG_SINCE = "2026-10-22"   # tickers last fully fetched before this date get one long refetch
# hourly bars (Yahoo keeps only ~730 days of 1h history; we accumulate from there)
US_HOURLY = ["GC=F", "SI=F", "SPY", "QQQ", "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL",
             "META", "MSTR", "COIN", "HOOD"]
US_SMOKE = ["AAPL", "TSLA", "NVDA", "SPY", "GC=F", "SI=F", "^VIX"]
US_SMOKE_HOURLY = ["GC=F", "TSLA"]

# ------------------------------------------------------------------ Binance (data.binance.vision)
BN_1D_START = "2017-01-01"   # daily bars for every USD-M perpetual
BN_1H_START = "2017-01-01"
BN_15M_START = "2022-01-01"
# intraday watchlist; detected stock perpetuals (e.g. TSLAUSDT) are added automatically
BN_WATCH = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
            "XAUUSDT", "XAGUSDT", "PAXGUSDT", "XAUTUSDT"]
BN_STOCK_PERP_SINCE = "2025-06-01"   # a stock-ticker-named perp first listed after this = stock perp
BN_SMOKE = ["BTCUSDT", "XAUUSDT", "PAXGUSDT", "TSLAUSDT"]

# spot pairs with long intraday history; PAXGUSDT is 1 troy ounce of gold and trades 24/7 like the
# XAUUSDT perp, so it carries gold back to 2020 for intraday backtests
BN_SPOT_WATCH = ["PAXGUSDT"]
BN_SPOT_INTERVALS = ["1h", "15m"]
BN_SPOT_START = "2020-01-01"
BN_SPOT_SMOKE = ["PAXGUSDT"]

# Dukascopy spot quotes (hourly, complete months only) for intraday gold/silver history before the
# Binance contracts existed
# large US tech names as of early 2021 (chosen by size then, not by what happened later), hourly
DK_STOCKS_1H = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "FB", "NVDA", "TSLA", "NFLX", "ADBE", "INTC", "CSCO",
                "AVGO", "QCOM", "TXN", "AMD", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "ORCL", "CRM",
                "PYPL", "INTU", "IBM", "DELL", "NXPI"]
# large non-tech US names as of early 2021, for out-of-sample checks of rules found on the tech list
DK_STOCKS_1H_OTHER = ["JPM", "BAC", "WFC", "GS", "V", "MA", "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "PG", "KO",
                      "PEP", "WMT", "COST", "HD", "MCD", "NKE", "DIS", "XOM", "CVX", "BA", "CAT", "HON", "UNP",
                      "T", "VZ", "CMCSA"]
DK_SYMBOLS = ["XAUUSD", "XAGUSD"] + [t + "USUSD" for t in DK_STOCKS_1H + DK_STOCKS_1H_OTHER]
DK_START = "2020-01"
# 1-minute files -> stored as 5-minute bars (dukascopy/5m). AMD/MU/DELL are Dukascopy's US-stock quotes
# (AMD.US/USD ...), regular session only; they back intraday tests of the Binance stock contracts.
DK_M1_SYMBOLS = ["XAUUSD", "XAGUSD", "AMDUSUSD", "MUUSUSD", "DELLUSUSD"]
DK_M1_START = "2020-01"
