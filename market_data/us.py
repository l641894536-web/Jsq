"""US stocks, ETFs, indices and gold/silver futures from Yahoo Finance (yfinance)."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from . import config as C
from .common import (Stage, load_state, merge_partitioned, normalize, read_csv, save_state,
                     write_csv)

P4 = ("float", 4)
DAILY_SCHEMA = {"ticker": "str", "date": "str", "open": P4, "high": P4, "low": P4, "close": P4,
                "adj_close": P4, "volume": "int"}
HOURLY_SCHEMA = {"ticker": "str", "ts": "str", "open": P4, "high": P4, "low": P4, "close": P4,
                 "volume": "int"}
EVENT_SCHEMA = {"ticker": "str", "date": "str", "dividend": ("float", 6), "split": ("float", 6)}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"}
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
THREADS = 6


SP500_CSV = ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/"
             "constituents.csv")


def _colname(c) -> str:
    c = c[-1] if isinstance(c, tuple) else c
    return str(c).split("[")[0].strip()


def _wiki_table(url: str, lo: int, hi: int) -> pd.DataFrame:
    html = requests.get(url, headers=UA, timeout=30).text
    tables = pd.read_html(StringIO(html))
    seen = []
    for t in tables:
        t = t.copy()
        t.columns = [_colname(c) for c in t.columns]
        cols = list(t.columns)
        seen.append(f"{len(t)}x{cols[:5]}")
        key = next((c for c in cols if c.lower() in ("symbol", "ticker", "ticker symbol")), None)
        if key and lo <= len(t) <= hi:
            name = next((c for c in ("Security", "Company", "Company name") if c in cols), None)
            sector = next((c for c in cols if "Sector" in c), None)
            return pd.DataFrame({
                "ticker": t[key].astype(str).str.strip().str.replace(".", "-", regex=False),
                "name": t[name].astype(str) if name else "",
                "sector": t[sector].astype(str) if sector else "",
            })
    raise RuntimeError(f"no constituent table at {url}; tables seen: {seen}")


def _sp500_csv() -> pd.DataFrame:
    t = pd.read_csv(StringIO(requests.get(SP500_CSV, headers=UA, timeout=30).text))
    return pd.DataFrame({"ticker": t["Symbol"].astype(str).str.replace(".", "-", regex=False),
                         "name": t.get("Security", ""), "sector": t.get("GICS Sector", "")})


def load_universe(root: Path, stage: Stage) -> pd.DataFrame:
    """S&P 500 + Nasdaq-100 (Wikipedia, with fallbacks), plus our fixed extras."""
    path = root / "us" / "meta" / "universe.csv"
    cached = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else None
    parts = []
    # Nasdaq-100 names outside the S&P 500 are listed statically in config.US_EXTRA_STOCKS
    # (Wikipedia's Nasdaq-100 page no longer parses cleanly).
    for src, fetchers in (("sp500", [lambda: _wiki_table(SP500_URL, 450, 560), _sp500_csv]),):
        got = None
        for f in fetchers:
            try:
                got = f()
                break
            except Exception as e:
                stage.error(f"universe {src}: {e}")
        if got is None and cached is not None:
            got = cached[cached["source"].str.contains(src)]
            stage.error(f"universe {src}: using cached list ({len(got)})")
        if got is not None:
            got = got.copy()
            got["source"] = src
            parts.append(got)
            stage.info[f"n_{src}"] = len(got)
    for src, lst in (("extra", C.US_EXTRA_STOCKS), ("etf", C.US_ETFS), ("index", C.US_INDICES),
                     ("future", C.US_FUTURES)):
        parts.append(pd.DataFrame({"ticker": lst, "name": "", "sector": "", "source": src}))
    uni = pd.concat(parts, ignore_index=True)
    uni = (uni.groupby("ticker", as_index=False)
              .agg({"name": "first", "sector": "first",
                    "source": lambda s: "|".join(sorted(set(";".join(s).split(";"))))}))
    write_csv(uni, path)
    stage.info["universe_size"] = len(uni)
    return uni


def _history(ticker: str, **kw) -> pd.DataFrame:
    import yfinance as yf
    err = None
    for attempt in range(3):
        try:
            return yf.Ticker(ticker).history(auto_adjust=False, **kw)
        except Exception as e:
            err = e
            time.sleep(4 * (attempt + 1) ** 2)
    raise err


def _daily_frames(ticker: str, h: pd.DataFrame):
    h = h[h["Close"].notna()]
    dates = pd.DatetimeIndex(h.index).strftime("%Y-%m-%d")
    bars = pd.DataFrame({
        "ticker": ticker, "date": dates,
        "open": h["Open"].values, "high": h["High"].values, "low": h["Low"].values,
        "close": h["Close"].values,
        "adj_close": (h["Adj Close"] if "Adj Close" in h.columns else h["Close"]).values,
        "volume": h["Volume"].values,
    })
    div = h["Dividends"].values if "Dividends" in h.columns else 0.0
    spl = h["Stock Splits"].values if "Stock Splits" in h.columns else 0.0
    ev = pd.DataFrame({"ticker": ticker, "date": dates, "dividend": div, "split": spl})
    ev = ev[(ev["dividend"].fillna(0) != 0) | (ev["split"].fillna(0) != 0)]
    return bars, ev


def run(root: Path, mode: str, deadline: float, universe: pd.DataFrame,
        stock_perps: list[str]) -> dict:
    st = Stage("us")
    try:
        base = root / "us"
        perp_underlyings = [s[:-4] for s in stock_perps]
        if mode == "smoke":
            tickers, hourly = list(C.US_SMOKE), list(C.US_SMOKE_HOURLY)
            us_start = "2025-01-01"
        else:
            tickers = sorted(set(universe["ticker"]) | set(perp_underlyings))
            hourly = list(dict.fromkeys(C.US_HOURLY + perp_underlyings))
            us_start = C.US_START
        st.info.update(n_tickers=len(tickers), n_hourly=len(hourly))

        now = datetime.now(timezone.utc)
        sunday = now.weekday() == 6
        state_path = base / "meta" / "fetch_state.csv"
        state = load_state(state_path, ["ticker", "fetched_through", "last_full"])
        sd = {r.ticker: (r.fetched_through, r.last_full) for r in state.itertuples()}

        def plan(t):
            ft, lf = sd.get(t, ("", ""))
            stale_full = not lf or (now.date() - datetime.fromisoformat(lf).date()).days >= 7
            if not ft or stale_full or sunday:
                return t, us_start, True
            start = (datetime.fromisoformat(ft) - timedelta(days=7)).strftime("%Y-%m-%d")
            return t, start, False

        def fetch(job):
            t, start, full = job
            if time.time() > deadline:
                return job, None, None, "deadline"
            try:
                h = _history(t, start=start, interval="1d", actions=True)
                if h is None or h.empty:
                    return job, None, None, ("no data" if full else None)
                bars, ev = _daily_frames(t, h)
                if not full and (ev["split"].fillna(0) != 0).any():   # split: refetch whole history
                    h = _history(t, start=us_start, interval="1d", actions=True)
                    bars, ev = _daily_frames(t, h)
                    job = (t, us_start, True)
                return job, bars, ev, None
            except Exception as e:
                return job, None, None, str(e)

        bars_all, ev_all, n_ok = [], [], 0
        new_state = dict(sd)
        today = now.strftime("%Y-%m-%d")
        with ThreadPoolExecutor(THREADS) as ex:
            for (t, start, full), bars, ev, err in ex.map(fetch, [plan(t) for t in tickers]):
                if err:
                    st.error(f"{t}: {err}")
                    continue
                if bars is not None:
                    bars_all.append(bars)
                    ev_all.append(ev)
                    n_ok += 1
                ft = bars["date"].max() if bars is not None and len(bars) else sd.get(t, ("", ""))[0]
                lf = today if full else sd.get(t, ("", ""))[1]
                new_state[t] = (ft, lf)
        st.info["tickers_ok"] = n_ok
        if bars_all:
            df = pd.concat(bars_all, ignore_index=True)
            st.info["rows_added_daily"] = int(merge_partitioned(
                df, base / "daily", ["ticker", "date"], "date", DAILY_SCHEMA))
            st.info["latest_daily"] = df["date"].max()
        ev = pd.concat(ev_all, ignore_index=True) if ev_all else pd.DataFrame()
        if len(ev):
            ev_path = base / "events.csv.xz"
            ev = normalize(ev, EVENT_SCHEMA)
            if ev_path.exists():
                ev = pd.concat([read_csv(ev_path, EVENT_SCHEMA), ev], ignore_index=True)
            ev = ev.drop_duplicates(["ticker", "date"], keep="last").sort_values(["ticker", "date"])
            write_csv(ev, ev_path)
        save_state(pd.DataFrame([{"ticker": k, "fetched_through": v[0], "last_full": v[1]}
                                 for k, v in sorted(new_state.items())]), state_path)
        st.log(f"daily ok {n_ok}/{len(tickers)}, +{st.info.get('rows_added_daily', 0)} rows")

        # ---- hourly
        hstate_path = base / "meta" / "hourly_state.csv"
        hstate = load_state(hstate_path, ["ticker", "last_ts"])
        hs = {r.ticker: r.last_ts for r in hstate.itertuples()}
        earliest = now - timedelta(days=729)
        if mode == "smoke":
            earliest = now - timedelta(days=30)
        frames = []
        for t in hourly:
            if time.time() > deadline:
                st.error("hourly: deadline reached")
                break
            lt = hs.get(t)
            start = earliest
            if lt:
                start = max(earliest, datetime.fromisoformat(lt).replace(tzinfo=timezone.utc) - timedelta(days=3))
            try:
                h = _history(t, start=start.strftime("%Y-%m-%d"), interval="1h", actions=False,
                             prepost=False)
                if h is None or h.empty:
                    st.error(f"hourly {t}: no data")
                    continue
                h = h[h["Close"].notna()]
                ts = pd.DatetimeIndex(h.index).tz_convert("UTC").strftime("%Y-%m-%d %H:%M")
                frames.append(pd.DataFrame({"ticker": t, "ts": ts, "open": h["Open"].values,
                                            "high": h["High"].values, "low": h["Low"].values,
                                            "close": h["Close"].values, "volume": h["Volume"].values}))
                hs[t] = ts.max()
            except Exception as e:
                st.error(f"hourly {t}: {e}")
        if frames:
            df = pd.concat(frames, ignore_index=True)
            st.info["rows_added_hourly"] = int(merge_partitioned(
                df, base / "hourly", ["ticker", "ts"], "ts", HOURLY_SCHEMA))
        save_state(pd.DataFrame([{"ticker": k, "last_ts": v} for k, v in sorted(hs.items())]),
                   hstate_path)
        st.info["hourly_ok"] = len(frames)
        st.info["ok"] = n_ok > 0.8 * len(tickers)
    except Exception as e:
        st.crash(e)
    return st.result()
