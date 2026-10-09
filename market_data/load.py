"""Read the market-data snapshot into pandas.

Get / refresh the data (branch `data`, single commit, refreshed daily by GitHub Actions):

    git clone --depth 1 -b data https://github.com/l641894536-web/Jsq.git ~/market-data
    # later: git -C ~/market-data fetch --depth 1 origin data && git -C ~/market-data reset --hard FETCH_HEAD

Then:

    import sys; sys.path.insert(0, "<path to this repo>")
    from market_data import load
    df = load.a_share(start="2024-01-01", adjust="hfq")
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("MARKET_DATA", Path.home() / "market-data"))
REPO = "https://github.com/l641894536-web/Jsq.git"
PRICE_COLS = ["open", "high", "low", "close", "preclose"]


def sync(path: Path = DATA) -> Path:
    """Clone or fast-forward the data snapshot."""
    path = Path(path)
    if (path / ".git").exists():
        subprocess.run(["git", "-C", str(path), "fetch", "-q", "--depth", "1", "origin", "data"], check=True)
        subprocess.run(["git", "-C", str(path), "reset", "-q", "--hard", "FETCH_HEAD"], check=True)
    else:
        subprocess.run(["git", "clone", "-q", "--depth", "1", "-b", "data", REPO, str(path)], check=True)
    return path


def status() -> dict:
    return json.loads((DATA / "status.json").read_text())


def _parts(sub: str, start: str | None, end: str | None, **read_kw) -> pd.DataFrame:
    files = sorted((DATA / sub).glob("*/*.csv.xz"))
    lo, hi = (start or "0000")[:7], (end or "9999")[:7]
    files = [f for f in files if lo <= f.name[:7] <= hi]
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(f, **read_kw) for f in files], ignore_index=True)


def _clip(df: pd.DataFrame, col: str, start, end) -> pd.DataFrame:
    if df.empty:
        return df
    if start:
        df = df[df[col] >= start]
    if end:
        df = df[df[col] <= (end if len(end) > 10 else end + " 99")]
    return df


# ------------------------------------------------------------------ A-shares

def a_share(start: str | None = None, end: str | None = None, codes=None,
            adjust: str | None = "hfq") -> pd.DataFrame:
    """Daily bars. adjust: None (raw), "hfq" (后复权), "qfq" (前复权, relative to the latest bar).
    Columns: date, code, open, high, low, close, preclose, volume, amount, turn(%), tradestatus,
    pctChg(%), peTTM, pbMRQ, isST."""
    df = _parts("a_share/daily", start, end, dtype={"date": str, "code": str})
    df = _clip(df, "date", start, end)
    if codes is not None:
        df = df[df["code"].isin(set([codes] if isinstance(codes, str) else codes))]
    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    if adjust and len(df):
        df = _adjust(df, adjust)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _adjust(df: pd.DataFrame, how: str) -> pd.DataFrame:
    """Adjustment factor built from the exchange's own ex-rights reference price:
    factor_t = prod(close_{s-1} / preclose_s), so adjusted returns equal pctChg exactly.
    (baostock's adj_factor table is kept on disk but has a few spurious records, e.g.
    sz.000001 2020-12-31, so it is not used.) hfq levels are relative to the first loaded bar;
    qfq equals raw prices on the last loaded bar."""
    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    prev_close = df.groupby("code")["close"].shift(1)
    ratio = (prev_close / df["preclose"]).where(df["preclose"] > 0).fillna(1.0)
    f = ratio.groupby(df["code"]).cumprod()
    if how == "qfq":
        f = f / f.groupby(df["code"]).transform("last")
    df["adj_factor"] = f
    for c in PRICE_COLS:
        df[c] = df[c] * f
    return df


def a_share_stocks() -> pd.DataFrame:
    """code, code_name, ipoDate, outDate, type, status(1 listed/0 delisted), industry (证监会)."""
    basic = pd.read_csv(DATA / "a_share" / "meta" / "stock_basic.csv", dtype=str, keep_default_na=False)
    basic = basic[basic["type"] == "1"]
    ind_path = DATA / "a_share" / "meta" / "industry.csv"
    if ind_path.exists():
        ind = pd.read_csv(ind_path, dtype=str, keep_default_na=False)[["code", "industry"]]
        basic = basic.merge(ind, on="code", how="left")
    return basic.reset_index(drop=True)


def a_share_index(codes=None, start=None, end=None) -> pd.DataFrame:
    df = pd.read_csv(DATA / "a_share" / "index_daily.csv.xz", dtype={"date": str, "code": str})
    df = _clip(df, "date", start, end)
    if codes is not None:
        df = df[df["code"].isin(set([codes] if isinstance(codes, str) else codes))]
    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def trade_dates() -> pd.Series:
    cal = pd.read_csv(DATA / "a_share" / "meta" / "trade_dates.csv", dtype=str)
    return pd.to_datetime(cal.loc[cal["is_trading_day"] == "1", "calendar_date"]).reset_index(drop=True)


# ------------------------------------------------------------------ US

def us_daily(tickers=None, start=None, end=None) -> pd.DataFrame:
    """ticker, date, open, high, low, close (split-adjusted), adj_close (split+dividend), volume.
    Futures (GC=F, SI=F, ...) are Yahoo's continuous front month: expect roll gaps."""
    df = _parts("us/daily", start, end, dtype={"ticker": str, "date": str})
    df = _clip(df, "date", start, end)
    if tickers is not None:
        df = df[df["ticker"].isin(set([tickers] if isinstance(tickers, str) else tickers))]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def us_hourly(tickers=None, start=None, end=None) -> pd.DataFrame:
    """ts is the bar open time in UTC."""
    df = _parts("us/hourly", start, end, dtype={"ticker": str, "ts": str})
    df = _clip(df, "ts", start, end)
    if tickers is not None:
        df = df[df["ticker"].isin(set([tickers] if isinstance(tickers, str) else tickers))]
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values(["ticker", "ts"]).reset_index(drop=True)


def us_universe() -> pd.DataFrame:
    return pd.read_csv(DATA / "us" / "meta" / "universe.csv", dtype=str, keep_default_na=False)


# ------------------------------------------------------------------ Binance USD-M perpetuals

def binance(interval: str = "1d", symbols=None, start=None, end=None) -> pd.DataFrame:
    """interval: 1d (all perps), 1h / 15m (watchlist). Time = bar open, UTC."""
    tcol = "date" if interval == "1d" else "ts"
    df = _parts(f"binance/um_{interval}", start, end, dtype={"symbol": str, tcol: str})
    df = _clip(df, tcol, start, end)
    if symbols is not None:
        df = df[df["symbol"].isin(set([symbols] if isinstance(symbols, str) else symbols))]
    df[tcol] = pd.to_datetime(df[tcol], utc=(interval != "1d"))
    return df.sort_values(["symbol", tcol]).reset_index(drop=True)


def binance_symbols() -> pd.DataFrame:
    return pd.read_csv(DATA / "binance" / "meta" / "um_symbols.csv", dtype={"symbol": str})
