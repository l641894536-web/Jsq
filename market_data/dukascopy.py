"""Spot gold / silver hourly candles from Dukascopy's public datafeed (interbank quotes, back to 2003).

Used for intraday backtests before the Binance gold contracts existed. Monthly hourly files:
  https://datafeed.dukascopy.com/datafeed/XAUUSD/2022/00/BID_candles_hour_1.bi5   (month is 0-based)
and daily files of 1-minute candles, which are stored here as 5-minute bars:
  https://datafeed.dukascopy.com/datafeed/XAUUSD/2022/00/03/BID_candles_min_1.bi5
Each file is LZMA-compressed; every 24-byte big-endian record is
  uint32 seconds-from-file-start (month or day), int32 open, int32 close, int32 low, int32 high, float32 volume
with prices stored as integers (divided by the instrument's point factor). Only complete months are
fetched; a month already on disk is not fetched again.
"""
from __future__ import annotations

import lzma
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from . import config as C
from .common import Stage, merge_partitioned, part_path, read_csv

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m0:02d}/BID_candles_hour_1.bi5"
URL_M1 = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m0:02d}/{d:02d}/BID_candles_min_1.bi5"
SCHEMA = {"symbol": "str", "ts": "str", "open": ("float", 5), "high": ("float", 5), "low": ("float", 5),
          "close": ("float", 5), "volume": ("float", 4)}
REC = struct.Struct(">Iiiiif")
PLAUSIBLE = {"XAUUSD": (200, 20000), "XAGUSD": (2, 500), "AMDUSUSD": (2, 3000), "MUUSUSD": (2, 5000), "DELLUSUSD": (2, 3000)}


def months(start: str, end_excl: str) -> list[str]:
    out, y, m = [], int(start[:4]), int(start[5:7])
    while f"{y}-{m:02d}" < end_excl:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse(sym: str, month: str, blob: bytes, day: int | None = None) -> pd.DataFrame:
    raw = lzma.decompress(blob) if blob else b""
    n = len(raw) // REC.size
    if n == 0:
        return pd.DataFrame(columns=list(SCHEMA))
    recs = [REC.unpack_from(raw, i * REC.size) for i in range(n)]
    df = pd.DataFrame(recs, columns=["sec", "open", "close", "low", "high", "volume"])
    lo, hi = PLAUSIBLE.get(sym, (0.5, 20000) if sym.endswith("USUSD") else (0, float("inf")))
    med = float(df["close"].median())
    factor = next((f for f in (1000, 100000, 100, 10000, 10) if lo <= med / f <= hi), 1000)
    for c in ("open", "close", "low", "high"):
        df[c] = df[c] / factor
    ok = ((df["low"] <= df[["open", "close"]].min(axis=1)) & (df["high"] >= df[["open", "close"]].max(axis=1))).mean()
    if ok < 0.99:   # field order guard: fall back to open, high, low, close if the bars are inconsistent
        df = df.rename(columns={"close": "high", "high": "close"})
        ok2 = ((df["low"] <= df[["open", "close"]].min(axis=1)) & (df["high"] >= df[["open", "close"]].max(axis=1))).mean()
        if ok2 < 0.99:
            raise ValueError(f"inconsistent candles in {sym} {month} ({ok:.2f}/{ok2:.2f})")
    t0 = datetime(int(month[:4]), int(month[5:7]), day or 1, tzinfo=timezone.utc)
    df["ts"] = (pd.Timestamp(t0) + pd.to_timedelta(df["sec"], unit="s")).dt.strftime("%Y-%m-%d %H:%M")
    df = df[~((df["volume"] <= 0) & (df["high"] == df["low"]))]       # weekend / holiday filler bars
    df.insert(0, "symbol", sym)
    return df[list(SCHEMA)]


def have(base: Path, sym: str, month: str) -> bool:
    p = part_path(base, month)
    if not p.exists():
        return False
    try:
        return (read_csv(p)["symbol"] == sym).any()
    except Exception:
        return False


def to_5m(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sym = df["symbol"].iloc[0]
    x = df.assign(ts=pd.to_datetime(df["ts"])).set_index("ts")
    b = x.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    b = b.reset_index()
    b["ts"] = b["ts"].dt.strftime("%Y-%m-%d %H:%M")
    b.insert(0, "symbol", sym)
    return b[list(SCHEMA)]


def fetch_month_m1(sess, sym: str, month: str, deadline: float):
    """All days of one month as 5-minute bars, or an error (then nothing is written for that month)."""
    y, mo = int(month[:4]), int(month[5:7])
    ndays = (pd.Timestamp(y, mo, 1) + pd.offsets.MonthEnd(0)).day
    out, bad = [], []
    for d in range(1, ndays + 1):
        if time.time() > deadline:
            return None, "deadline"
        if pd.Timestamp(y, mo, d).dayofweek == 5:      # Saturday: market closed
            continue
        url = URL_M1.format(sym=sym, y=y, m0=mo - 1, d=d)
        err = None
        for attempt in range(6):
            try:
                r = sess.get(url, timeout=60)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                if r.content:
                    out.append(to_5m(parse(sym, month, r.content, day=d)))
                err = None
                break
            except Exception as e:
                err = str(e)
                time.sleep(5 * (attempt + 1))
        if err:
            bad.append(f"{d:02d}: {err[:120]}")
            if len(bad) > 2:                      # more than two broken days: retry the whole month next run
                return None, "; ".join(bad)
        time.sleep(0.15)
    out = [o for o in out if len(o)]
    df = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=list(SCHEMA))
    # a day or two the feed keeps refusing (often holidays / near-empty Sundays) should not block a month forever
    return df, ("partial:" + "; ".join(bad)) if bad else None


def run(root: Path, mode: str, deadline: float) -> dict:
    st = Stage("dukascopy")
    try:
        base = root / "dukascopy" / "1h"
        now = datetime.now(timezone.utc)
        cur = f"{now.year}-{now.month:02d}"
        start = C.DK_START if mode == "full" else months("2000-01", cur)[-2]
        todo = [(s, m) for s in C.DK_SYMBOLS for m in months(start, cur) if not have(base, s, m)]
        st.log(f"{len(todo)} symbol-months to fetch")
        sess = requests.Session()
        sess.headers["User-Agent"] = "Mozilla/5.0 (market-data-bot)"

        def fetch(job):
            s, m = job
            if time.time() > deadline:
                return job, None, "deadline"
            url = URL.format(sym=s, y=m[:4], m0=int(m[5:7]) - 1)
            for attempt in range(6):
                try:
                    r = sess.get(url, timeout=60)
                    if r.status_code == 404:
                        return job, None, None
                    r.raise_for_status()
                    return job, parse(s, m, r.content), None
                except Exception as e:
                    err = str(e)
                    time.sleep(5 * (attempt + 1))   # the feed answers 503 when hit too fast
            return job, None, err

        parts, n_ok = [], 0
        with ThreadPoolExecutor(2) as ex:              # be gentle with a free public feed
            for (s, m), df, err in ex.map(fetch, todo):
                if err:
                    st.error(f"{s} {m}: {err}")
                elif df is not None and len(df):
                    parts.append(df); n_ok += 1
        added = merge_partitioned(pd.concat(parts, ignore_index=True), base, ["symbol", "ts"], "ts", SCHEMA) if parts else 0
        st.info.update(months_fetched=n_ok, rows_added=int(added), symbols=C.DK_SYMBOLS)
        st.log(f"1h: +{added} rows from {n_ok} files")

        # 5-minute bars from daily 1-minute files, one complete month at a time
        base5 = root / "dukascopy" / "5m"
        start5 = C.DK_M1_START if mode == "full" else months("2000-01", cur)[-2]
        todo5 = [(s, m) for s in C.DK_M1_SYMBOLS for m in months(start5, cur) if not have(base5, s, m)]
        st.log(f"5m: {len(todo5)} symbol-months to fetch")
        n5, added5, errs5 = 0, 0, 0
        with ThreadPoolExecutor(3) as ex:
            futs = ex.map(lambda j: (j, *fetch_month_m1(sess, j[0], j[1], deadline)), todo5)
            for (s, m), df, err in futs:
                if err and err.startswith("partial:"):
                    st.info.setdefault("days_missing_5m", []).append(f"{s} {m} {err[8:]}"[:200])
                    err = None
                if err:
                    errs5 += 1
                    if err != "deadline":
                        st.error(f"5m {s} {m}: {err}")
                    continue
                if df is not None and len(df):
                    added5 += merge_partitioned(df, base5, ["symbol", "ts"], "ts", SCHEMA)
                    n5 += 1
        left = sum(1 for s in C.DK_M1_SYMBOLS for m in months(start5, cur) if not have(base5, s, m))
        st.info.update(months_5m=n5, rows_added_5m=int(added5), months_5m_left=left)
        st.log(f"5m: +{added5} rows from {n5} months, {left} months still missing")
        st.info["ok"] = st.n_errors <= max(2, 0.05 * (len(todo) + len(todo5)))
    except Exception as e:
        st.crash(e)
    return st.result()
