"""Binance USD-M perpetual klines from the public archive at data.binance.vision.

The REST API (fapi.binance.com) refuses US IPs, which is where GitHub runners live; the archive
is Binance's own bulk-download site and is not geo-restricted. Daily files appear the next UTC day,
so the newest bar here is always yesterday (UTC).
"""
from __future__ import annotations

import io
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

from . import config as C
from .common import Stage, load_state, merge_partitioned, save_state, write_csv

DL = "https://data.binance.vision/"
LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
         "trades", "taker_buy_volume", "taker_buy_quote_volume"]
VALUE_COLS = ["open", "high", "low", "close", "volume", "quote_volume", "trades",
              "taker_buy_volume", "taker_buy_quote_volume"]
INTERVAL_MS = {"1d": 86_400_000, "1h": 3_600_000, "15m": 900_000}
THREADS = 24


def time_col(interval: str) -> str:
    return "date" if interval == "1d" else "ts"


def schema(interval: str) -> dict:
    s = {"symbol": "str", time_col(interval): "str"}
    s.update({c: "str" for c in VALUE_COLS})   # keep Binance's own decimal strings untouched
    return s


def _session() -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(pool_connections=THREADS + 8, pool_maxsize=THREADS + 8)
    s.mount("https://", adapter)
    s.headers["User-Agent"] = "Mozilla/5.0 (market-data-bot)"
    return s


def _get(sess, url, params=None, allow_404=False):
    last = None
    for attempt in range(4):
        try:
            r = sess.get(url, params=params, timeout=60)
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in (403, 451):
                raise requests.HTTPError(f"HTTP {r.status_code} (blocked?) for {r.url}")
            if r.status_code >= 400:
                raise requests.HTTPError(f"HTTP {r.status_code} for {r.url}")
            return r
        except requests.HTTPError as e:
            last = e
            if "blocked" in str(e):
                raise
        except Exception as e:  # network hiccup
            last = e
        time.sleep(1.5 * (2 ** attempt))
    raise last


def s3_list(sess, prefix: str, delimiter: bool = False, max_keys: int | None = None):
    keys, prefixes, marker = [], [], ""
    for _ in range(500):
        params = {"prefix": prefix}
        if delimiter:
            params["delimiter"] = "/"
        if max_keys:
            params["max-keys"] = str(max_keys)
        if marker:
            params["marker"] = marker
        root = ET.fromstring(_get(sess, LIST_URL, params).content)
        pk = [c.findtext("s3:Key", namespaces=NS) for c in root.findall("s3:Contents", NS)]
        pp = [p.findtext("s3:Prefix", namespaces=NS) for p in root.findall("s3:CommonPrefixes", NS)]
        keys += pk
        prefixes += pp
        if max_keys or root.findtext("s3:IsTruncated", namespaces=NS) != "true":
            break
        marker = root.findtext("s3:NextMarker", namespaces=NS) or (pk[-1] if pk else pp[-1])
    return keys, prefixes


def parse_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f, header=None, dtype=str, keep_default_na=False)
    if df.empty:
        return pd.DataFrame(columns=KCOLS)
    if not str(df.iat[0, 0]).strip().isdigit():          # newer files carry a header row
        df = df.iloc[1:]
    df = df.iloc[:, :11].copy()
    df.columns = KCOLS
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    df = df[ot.notna()].copy()
    ot = ot[ot.notna()].astype("int64")
    df["open_time"] = ot.where(ot < 10**14, ot // 1000)   # some archives switched to microseconds
    return df.drop(columns=["close_time"])


def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def _next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y + (mo == 12)}-{1 if mo == 12 else mo + 1:02d}"


def _prev_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y - (mo == 1)}-{12 if mo == 1 else mo - 1:02d}"


def plan_urls(sess, sym: str, interval: str, last_ms: int | None, min_start: date,
              today: date) -> list[str]:
    if last_ms:
        frm = datetime.fromtimestamp((last_ms + INTERVAL_MS[interval]) / 1000, tz=timezone.utc).date()
        frm = max(frm, min_start)
    else:
        frm = min_start
    if frm >= today:
        return []
    cur_m, frm_m = _month(today), _month(frm)
    urls, covered = [], []
    if frm_m < cur_m:
        keys, _ = s3_list(sess, f"data/futures/um/monthly/klines/{sym}/{interval}/")
        for k in keys:
            if k.endswith(".zip"):
                m = k[-11:-4]
                if frm_m <= m < cur_m:
                    urls.append(DL + k)
                    covered.append(m)
    m = _next_month(max(covered)) if covered else max(frm_m, _prev_month(cur_m))
    while m <= cur_m:
        keys, _ = s3_list(sess, f"data/futures/um/daily/klines/{sym}/{interval}/{sym}-{interval}-{m}")
        for k in keys:
            if k.endswith(".zip") and frm.isoformat() <= k[-14:-4] < today.isoformat():
                urls.append(DL + k)
        m = _next_month(m)
    return urls


def detect_stock_perps(sess, symbols: list[str], us_tickers: set[str], stage: Stage) -> list[str]:
    found = []
    for s in symbols:
        if not s.endswith("USDT") or s[:-4] not in us_tickers:
            continue
        try:
            keys, _ = s3_list(sess, f"data/futures/um/daily/klines/{s}/1d/", max_keys=2)
            zips = [k for k in keys if k.endswith(".zip")]
            if zips and zips[0][-14:-4] >= C.BN_STOCK_PERP_SINCE:
                found.append(s)
        except Exception as e:
            stage.error(f"detect {s}: {e}")
    return found


def _recent(root: Path, sub: str, months: int = 5) -> pd.DataFrame:
    files = sorted((root / sub).glob("*/*.csv.xz"))[-months:]
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files],
                     ignore_index=True)


def validate_stock_perps(root: Path, cands: list[str], stage: Stage) -> list[str]:
    """Name matches are not enough (crypto tokens C, F, O, MET... share stock tickers; CLUSDT is
    crude oil). Keep a candidate only if its price tracks the US share: median price ratio within
    3% and non-negative daily-return correlation. Too-new candidates (<3 shared days) are kept."""
    bn, us_ = _recent(root, "binance/um_1d"), _recent(root, "us/daily")
    if bn.empty or us_.empty:
        return cands
    bn = bn[bn["symbol"].isin(cands)][["symbol", "date", "close"]].copy()
    bn["ticker"] = bn["symbol"].str[:-4]
    m = bn.merge(us_[["ticker", "date", "close"]], on=["ticker", "date"], suffixes=("_bn", "_us"))
    for c in ("close_bn", "close_us"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    keep, rejected = [], {}
    for s in cands:
        g = m[m["symbol"] == s].sort_values("date")
        if len(g) < 3:
            keep.append(s)
            continue
        ratio = float((g["close_bn"] / g["close_us"]).median())
        corr = g["close_bn"].pct_change().corr(g["close_us"].pct_change()) if len(g) >= 30 else 1.0
        if 0.97 <= ratio <= 1.03 and not corr < 0:
            keep.append(s)
        else:
            rejected[s] = {"ratio": round(ratio, 4), "corr": None if pd.isna(corr) else round(float(corr), 2)}
    stage.info["stock_perps_rejected"] = rejected
    return keep


def run(root: Path, mode: str, deadline: float, us_tickers: set[str]) -> tuple[dict, list[str]]:
    st = Stage("binance")
    stock_perps: list[str] = []
    try:
        base = root / "binance"
        sess = _session()
        today = datetime.now(timezone.utc).date()

        _, prefixes = s3_list(sess, "data/futures/um/daily/klines/", delimiter=True)
        symbols = sorted({p.rstrip("/").split("/")[-1] for p in prefixes})
        st.log(f"{len(symbols)} USD-M symbols in archive")
        st.info["n_symbols"] = len(symbols)
        if not symbols:
            raise RuntimeError("symbol listing came back empty")

        stock_perps = detect_stock_perps(sess, symbols, us_tickers, st)
        stock_perps = validate_stock_perps(root, stock_perps, st)
        st.info["stock_perps"] = stock_perps
        st.log(f"stock perps: {stock_perps}")
        write_csv(pd.DataFrame({"symbol": symbols,
                                "stock_perp": [int(s in stock_perps) for s in symbols]}),
                  base / "meta" / "um_symbols.csv")

        watch = [s for s in C.BN_WATCH if s in symbols] + stock_perps
        if mode == "smoke":
            daily_syms = [s for s in C.BN_SMOKE if s in symbols]
            watch = daily_syms
            starts = {"1d": date(2026, 1, 1), "1h": today - timedelta(days=40),
                      "15m": today - timedelta(days=10)}
        else:
            daily_syms = symbols
            starts = {"1d": date.fromisoformat(C.BN_1D_START),
                      "1h": date.fromisoformat(C.BN_1H_START),
                      "15m": date.fromisoformat(C.BN_15M_START)}
        st.info["watchlist"] = watch

        state_path = base / "meta" / "fetch_state.csv"
        state = load_state(state_path, ["symbol", "interval", "last_ms"])
        last = {(r.symbol, r.interval): int(r.last_ms) for r in state.itertuples() if r.last_ms}
        sunday = today.weekday() == 6

        jobs = []
        for interval, syms in (("1d", daily_syms), ("1h", watch), ("15m", watch)):
            for s in syms:
                lm = last.get((s, interval))
                stale = lm is not None and (time.time() * 1000 - lm) > 60 * 86_400_000
                if stale and not sunday:
                    continue   # long-dead contract: re-check weekly only
                jobs.append((s, interval, lm))
        st.log(f"planning {len(jobs)} symbol/interval jobs")

        def _plan(job):
            s, interval, lm = job
            try:
                return job, plan_urls(sess, s, interval, lm, starts[interval], today), None
            except Exception as e:
                return job, [], str(e)

        downloads = []
        with ThreadPoolExecutor(THREADS) as ex:
            for job, urls, err in ex.map(_plan, jobs):
                if err:
                    st.error(f"plan {job[0]} {job[1]}: {err}")
                downloads += [(job[0], job[1], u) for u in urls]
        st.log(f"{len(downloads)} archive files to download")
        st.info["files_planned"] = len(downloads)

        def _dl(item):
            s, interval, url = item
            if time.time() > deadline:
                return item, None, "deadline"
            try:
                r = _get(sess, url, allow_404=True)
                if r is None:
                    return item, None, None
                df = parse_zip(r.content)
                df.insert(0, "symbol", s)
                return item, df, None
            except Exception as e:
                return item, None, str(e)

        frames = {"1d": [], "1h": [], "15m": []}
        n_ok = 0
        with ThreadPoolExecutor(THREADS) as ex:
            for (s, interval, url), df, err in ex.map(_dl, downloads):
                if err:
                    st.error(f"download {url}: {err}")
                elif df is not None and not df.empty:
                    frames[interval].append(df)
                    n_ok += 1
        st.info["files_ok"] = n_ok

        new_last = dict(last)
        for interval, parts in frames.items():
            if not parts:
                st.info[f"rows_added_{interval}"] = 0
                continue
            df = pd.concat(parts, ignore_index=True)
            df = df.drop_duplicates(["symbol", "open_time"], keep="last")
            prev = df["symbol"].map(lambda s: last.get((s, interval), -1))
            df = df[df["open_time"] > prev]
            fmt = "%Y-%m-%d" if interval == "1d" else "%Y-%m-%d %H:%M"
            df[time_col(interval)] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime(fmt)
            for s, mx in df.groupby("symbol")["open_time"].max().items():
                new_last[(s, interval)] = int(mx)
            added = merge_partitioned(df, base / f"um_{interval}", ["symbol", time_col(interval)],
                                      time_col(interval), schema(interval))
            st.info[f"rows_added_{interval}"] = int(added)
            st.log(f"{interval}: +{added} rows")

        save_state(pd.DataFrame([{"symbol": k[0], "interval": k[1], "last_ms": str(v)}
                                 for k, v in sorted(new_last.items())]), state_path)
        st.info["latest_1d"] = max((datetime.fromtimestamp(v / 1000, tz=timezone.utc).date().isoformat()
                                    for (s, i), v in new_last.items() if i == "1d"), default=None)
        st.info["ok"] = (st.n_errors <= max(3, 0.05 * len(jobs))
                         and (st.info.get("files_ok", 0) > 0 or len(downloads) == 0))
    except Exception as e:
        st.crash(e)
    return st.result(), stock_perps
