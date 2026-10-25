"""Spot gold / silver hourly candles from Dukascopy's public datafeed (interbank quotes, back to 2003).

Used for intraday backtests before the Binance gold contracts existed. Monthly hourly files:
  https://datafeed.dukascopy.com/datafeed/XAUUSD/2022/00/BID_candles_hour_1.bi5   (month is 0-based)
Each file is LZMA-compressed; every 24-byte big-endian record is
  uint32 seconds-from-month-start, int32 open, int32 close, int32 low, int32 high, float32 volume
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
SCHEMA = {"symbol": "str", "ts": "str", "open": ("float", 5), "high": ("float", 5), "low": ("float", 5),
          "close": ("float", 5), "volume": ("float", 4)}
REC = struct.Struct(">Iiiiif")
PLAUSIBLE = {"XAUUSD": (200, 20000), "XAGUSD": (2, 500)}


def months(start: str, end_excl: str) -> list[str]:
    out, y, m = [], int(start[:4]), int(start[5:7])
    while f"{y}-{m:02d}" < end_excl:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse(sym: str, month: str, blob: bytes) -> pd.DataFrame:
    raw = lzma.decompress(blob) if blob else b""
    n = len(raw) // REC.size
    if n == 0:
        return pd.DataFrame(columns=list(SCHEMA))
    recs = [REC.unpack_from(raw, i * REC.size) for i in range(n)]
    df = pd.DataFrame(recs, columns=["sec", "open", "close", "low", "high", "volume"])
    lo, hi = PLAUSIBLE.get(sym, (0, float("inf")))
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
    t0 = datetime(int(month[:4]), int(month[5:7]), 1, tzinfo=timezone.utc)
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
        st.log(f"+{added} rows from {n_ok} files")
        st.info["ok"] = st.n_errors <= max(2, 0.05 * len(todo))
    except Exception as e:
        st.crash(e)
    return st.result()
