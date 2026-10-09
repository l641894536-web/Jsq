"""What to fetch. Edit the lists here; the next run picks the changes up."""

# ------------------------------------------------------------------ A-shares (baostock)
A_START = "2015-01-01"
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
