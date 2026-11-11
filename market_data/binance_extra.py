"""Binance positioning data from the public archive (data.binance.vision), for "is the long side crowded?" research.

- Funding rate history (monthly files, every settlement since 2020) for the workbench symbols
  -> binance/funding/<SYMBOL>.csv.xz   columns: ts (UTC "YYYY-MM-DD HH:MM"), rate, interval_h
- Futures metrics (5-minute open interest, long/short ratios, taker buy/sell ratio, daily files from ~2021-12)
  for the 7 main coins, rolled up to hours
  -> binance/metrics_1h/YYYY/YYYY-MM.csv.xz   columns: symbol, ts, oi, oi_usd, top_ls_acct, top_ls_pos, ls_acct, taker_ratio
     (oi / oi_usd = last value in the hour; ratios = mean of the 5-minute values)

Monthly funding files appear after the month ends, daily metrics files the next UTC day.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone, datetime
from pathlib import Path
import time

import pandas as pd

from .binance import DL, _get, _session, s3_list
from .common import Stage, load_state, merge_partitioned, read_csv, save_state, write_csv

FUND_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
             "XAUUSDT", "XAGUSDT", "AMDUSDT", "MUUSDT", "DELLUSDT", "NVDAUSDT", "TSLAUSDT", "SPCXUSDT"]
METRIC_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]
FUND_START, METRIC_START = "2020-01", date(2021, 12, 1)
MCOLS = ["oi", "oi_usd", "top_ls_acct", "top_ls_pos", "ls_acct", "taker_ratio"]
M_SCHEMA = {"symbol": "str", "ts": "str", **{c: "str" for c in MCOLS}}
THREADS = 24


def _read_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f, header=None, dtype=str, keep_default_na=False)
    if not df.empty and not str(df.iat[0, 0]).strip()[:1].isdigit():
        df.columns = [str(c).strip() for c in df.iloc[0]]
        df = df.iloc[1:].reset_index(drop=True)
    return df


def _parse_funding(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ts", "rate", "interval_h"])
    if "calc_time" not in df.columns:      # headerless: calc_time, funding_interval_hours, last_funding_rate
        df = df.iloc[:, :3].copy(); df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
    t = pd.to_numeric(df["calc_time"], errors="coerce")
    df = df[t.notna()].copy(); t = t[t.notna()].astype("int64")
    t = t.where(t < 10**14, t // 1000)
    return pd.DataFrame({"ts": pd.to_datetime(t, unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M"),
                         "rate": df["last_funding_rate"].astype(str).str.strip(),
                         "interval_h": df.get("funding_interval_hours", pd.Series([""] * len(df))).astype(str).str.strip()})


def _parse_metrics(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=list(M_SCHEMA))
    if "create_time" not in df.columns:
        df = df.iloc[:, :8].copy()
        df.columns = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
                      "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
    ts = pd.to_datetime(df["create_time"], errors="coerce", utc=True)
    if ts.isna().all():
        ts = pd.to_datetime(pd.to_numeric(df["create_time"], errors="coerce"), unit="ms", utc=True)
    src = {"oi": "sum_open_interest", "oi_usd": "sum_open_interest_value", "top_ls_acct": "count_toptrader_long_short_ratio",
           "top_ls_pos": "sum_toptrader_long_short_ratio", "ls_acct": "count_long_short_ratio", "taker_ratio": "sum_taker_long_short_vol_ratio"}
    x = pd.DataFrame({k: pd.to_numeric(df[v], errors="coerce") if v in df.columns else float("nan") for k, v in src.items()})
    x["h"] = ts.dt.floor("h")
    x = x[x["h"].notna()].sort_values("h")
    g = x.groupby("h")
    out = pd.concat([g[["oi", "oi_usd"]].last(), g[["top_ls_acct", "top_ls_pos", "ls_acct", "taker_ratio"]].mean()], axis=1).reset_index()
    out.insert(0, "symbol", sym)
    out["ts"] = out.pop("h").dt.strftime("%Y-%m-%d %H:%M")
    for c in MCOLS:
        out[c] = out[c].map(lambda v: "" if pd.isna(v) else f"{v:.6g}")
    return out[list(M_SCHEMA)]


def _keys(sess, prefix: str) -> list[str]:
    keys, _ = s3_list(sess, prefix)
    return sorted(k for k in keys if k.endswith(".zip"))


def run(root: Path, mode: str, deadline: float) -> dict:
    """Downloads exactly the files the archive lists (s3 listing), newer than what we already hold.
    State v2: the first version guessed URLs, got 404s everywhere and still advanced its state, so it is ignored."""
    st = Stage("binance_extra")
    try:
        base = root / "binance"
        sess = _session()
        state_path = base / "meta" / "extra_state_v2.csv"
        state = load_state(state_path, ["symbol", "kind", "last"])
        last = {(r.symbol, r.kind): r.last for r in state.itertuples() if r.last}
        fsyms = FUND_SYMS[:2] if mode == "smoke" else FUND_SYMS
        msyms = METRIC_SYMS[:1] if mode == "smoke" else METRIC_SYMS

        # ---- what does the archive hold? (logged so a wrong path is visible in the run log)
        try:
            _, pm = s3_list(sess, "data/futures/um/monthly/", delimiter=True)
            _, pdd = s3_list(sess, "data/futures/um/daily/", delimiter=True)
            st.info["archive_monthly"] = [x.rstrip("/").split("/")[-1] for x in pm]
            st.info["archive_daily"] = [x.rstrip("/").split("/")[-1] for x in pdd]
            st.log(f"archive monthly: {st.info['archive_monthly']} daily: {st.info['archive_daily']}")
        except Exception as e:
            st.error(f"listing datasets: {e}")

        # ---- funding (monthly files)
        jobs = []
        for s in fsyms:
            if time.time() > deadline:
                break
            try:
                ks = _keys(sess, f"data/futures/um/monthly/fundingRate/{s}/")
            except Exception as e:
                st.error(f"list funding {s}: {e}"); continue
            m0 = last.get((s, "funding"), "")
            for k in ks:
                m = k.rsplit("-fundingRate-", 1)[-1][:7]
                if m > m0 and (mode != "smoke" or m >= "2026-08"):
                    jobs.append((s, m, k))
        st.log(f"funding: {len(jobs)} monthly files listed to fetch")

        def _dl_f(job):
            s, m, k = job
            if time.time() > deadline:
                return job, None, "deadline"
            try:
                r = _get(sess, DL + k, allow_404=True)
                return job, (None if r is None else _parse_funding(_read_zip(r.content))), None
            except Exception as e:
                return job, None, str(e)

        got, done_f = {}, {}
        with ThreadPoolExecutor(THREADS) as ex:
            for (s, m, k), df, err in ex.map(_dl_f, jobs):
                if err:
                    if err != "deadline":
                        st.error(f"funding {s} {m}: {err}")
                    continue
                if df is not None and not df.empty:
                    got.setdefault(s, []).append(df); done_f.setdefault(s, []).append(m)
        n_rows = 0
        for s, parts in got.items():
            p = base / "funding" / f"{s}.csv.xz"
            new = pd.concat(parts, ignore_index=True)
            old = read_csv(p) if p.exists() else pd.DataFrame(columns=new.columns)
            comb = pd.concat([old.astype(str), new.astype(str)], ignore_index=True).drop_duplicates("ts", keep="last").sort_values("ts")
            n_rows += len(comb) - len(old)
            write_csv(comb, p)
            last[(s, "funding")] = max(done_f[s])
        st.info["funding_rows_added"] = int(n_rows)
        st.info["funding_symbols"] = sorted(got)

        # ---- metrics (daily files)
        jobs = []
        for s in msyms:
            if time.time() > deadline:
                break
            try:
                ks = _keys(sess, f"data/futures/um/daily/metrics/{s}/")
            except Exception as e:
                st.error(f"list metrics {s}: {e}"); continue
            d0 = last.get((s, "metrics"), "")
            cut = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat() if mode == "smoke" else ""
            for k in ks:
                d = k.rsplit("-metrics-", 1)[-1][:10]
                if d > d0 and d >= cut:
                    jobs.append((s, d, k))
        if jobs:
            st.log(f"metrics: {len(jobs)} daily files listed to fetch, e.g. {jobs[0][2]}")
        else:
            st.log("metrics: nothing new listed")

        def _dl_m(job):
            s, d, k = job
            if time.time() > deadline:
                return job, None, "deadline"
            try:
                r = _get(sess, DL + k, allow_404=True)
                return job, (None if r is None else _parse_metrics(_read_zip(r.content), s)), None
            except Exception as e:
                return job, None, str(e)

        frames, ok_days = [], {}
        with ThreadPoolExecutor(THREADS) as ex:
            for (s, d, k), df, err in ex.map(_dl_m, jobs):
                if err:
                    if err != "deadline":
                        st.error(f"metrics {s} {d}: {err}")
                    continue
                if df is not None:
                    frames.append(df); ok_days.setdefault(s, set()).add(d)
        added = 0
        if frames:
            added = merge_partitioned(pd.concat(frames, ignore_index=True), base / "metrics_1h", ["symbol", "ts"], "ts", M_SCHEMA)
        for s, ds in ok_days.items():
            # advance only through days with no gap among the listed-and-fetched files
            todo = sorted(d for (s2, d, _k) in jobs if s2 == s)
            for d in todo:
                if d in ds:
                    last[(s, "metrics")] = d
                else:
                    break
        st.info["metrics_rows_added"] = int(added)
        st.info["metrics_latest"] = {s: last.get((s, "metrics")) for s in msyms}
        st.info["funding_latest"] = {s: last.get((s, "funding")) for s in fsyms}
        save_state(pd.DataFrame([{"symbol": k[0], "kind": k[1], "last": v} for k, v in sorted(last.items())]), state_path)
        st.info["ok"] = st.n_errors <= 20
    except Exception as e:
        st.crash(e)
    return st.result()
