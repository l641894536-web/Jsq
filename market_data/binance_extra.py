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

from .binance import DL, _get, _session, _month, _next_month
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


def run(root: Path, mode: str, deadline: float) -> dict:
    st = Stage("binance_extra")
    try:
        base = root / "binance"
        sess = _session()
        today = datetime.now(timezone.utc).date()
        state_path = base / "meta" / "extra_state.csv"
        state = load_state(state_path, ["symbol", "kind", "last"])
        last = {(r.symbol, r.kind): r.last for r in state.itertuples() if r.last}
        fsyms = FUND_SYMS[:2] if mode == "smoke" else FUND_SYMS
        msyms = METRIC_SYMS[:1] if mode == "smoke" else METRIC_SYMS
        cur_month = _month(today)

        # ---- funding: one file per symbol per finished month
        jobs = []
        for s in fsyms:
            m = _next_month(last[(s, "funding")]) if (s, "funding") in last else ("2026-08" if mode == "smoke" else FUND_START)
            while m < cur_month:
                jobs.append((s, m)); m = _next_month(m)
        st.log(f"funding: {len(jobs)} monthly files to try")

        def _dl_f(job):
            s, m = job
            if time.time() > deadline:
                return job, None, "deadline"
            try:
                r = _get(sess, f"{DL}data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip", allow_404=True)
                return job, (None if r is None else _parse_funding(_read_zip(r.content))), None
            except Exception as e:
                return job, None, str(e)

        got: dict = {}
        done_f: dict = {}
        with ThreadPoolExecutor(THREADS) as ex:
            for (s, m), df, err in ex.map(_dl_f, jobs):
                if err:
                    if err != "deadline":
                        st.error(f"funding {s} {m}: {err}")
                    continue
                done_f.setdefault(s, []).append(m)
                if df is not None and not df.empty:
                    got.setdefault(s, []).append(df)
        n_rows = 0
        for s, parts in got.items():
            p = base / "funding" / f"{s}.csv.xz"
            new = pd.concat(parts, ignore_index=True)
            old = read_csv(p) if p.exists() else pd.DataFrame(columns=new.columns)
            comb = pd.concat([old.astype(str), new.astype(str)], ignore_index=True).drop_duplicates("ts", keep="last").sort_values("ts")
            n_rows += len(comb) - len(old)
            write_csv(comb, p)
        for s, ms in done_f.items():   # advance only over a gap-free run of finished months
            ms = sorted(ms); m0 = _next_month(last[(s, "funding")]) if (s, "funding") in last else ms[0]
            while m0 in ms:
                last[(s, "funding")] = m0; m0 = _next_month(m0)
        st.info["funding_rows_added"] = int(n_rows)
        st.info["funding_symbols"] = sorted(got)

        # ---- metrics: daily files, roll up to hours
        jobs = []
        for s in msyms:
            d = date.fromisoformat(last[(s, "metrics")]) + timedelta(days=1) if (s, "metrics") in last else (today - timedelta(days=5) if mode == "smoke" else METRIC_START)
            while d < today:
                jobs.append((s, d)); d += timedelta(days=1)
        st.log(f"metrics: {len(jobs)} daily files to try")

        def _dl_m(job):
            s, d = job
            if time.time() > deadline:
                return job, None, "deadline"
            try:
                r = _get(sess, f"{DL}data/futures/um/daily/metrics/{s}/{s}-metrics-{d.isoformat()}.zip", allow_404=True)
                return job, (None if r is None else _parse_metrics(_read_zip(r.content), s)), None
            except Exception as e:
                return job, None, str(e)

        frames, ok_days = [], {}
        with ThreadPoolExecutor(THREADS) as ex:
            for (s, d), df, err in ex.map(_dl_m, jobs):
                if err:
                    if err != "deadline":
                        st.error(f"metrics {s} {d}: {err}")
                    continue
                if df is None:
                    if d >= today - timedelta(days=2):
                        continue          # not published yet: try again next run
                else:
                    frames.append(df)
                ok_days.setdefault(s, set()).add(d)
        added = 0
        if frames:
            added = merge_partitioned(pd.concat(frames, ignore_index=True), base / "metrics_1h", ["symbol", "ts"], "ts", M_SCHEMA)
        for s, ds in ok_days.items():
            d0 = date.fromisoformat(last[(s, "metrics")]) + timedelta(days=1) if (s, "metrics") in last else min(ds)
            while d0 in ds:
                last[(s, "metrics")] = d0.isoformat(); d0 += timedelta(days=1)
        st.info["metrics_rows_added"] = int(added)
        st.info["metrics_latest"] = {s: last.get((s, "metrics")) for s in msyms}
        st.info["funding_latest"] = {s: last.get((s, "funding")) for s in fsyms}
        save_state(pd.DataFrame([{"symbol": k[0], "kind": k[1], "last": v} for k, v in sorted(last.items())]), state_path)
        st.info["ok"] = st.n_errors <= 20
    except Exception as e:
        st.crash(e)
    return st.result()
