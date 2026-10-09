"""A-share daily bars, adjustment factors, indices and metadata from baostock.

Bars are stored UNADJUSTED (adjustflag=3) together with baostock's adjustment-factor table, so
forward/backward-adjusted prices can be rebuilt at load time and never go stale.
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .common import (Stage, load_state, merge_partitioned, normalize, replace_rows, save_state,
                     write_csv)

FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg,peTTM,pbMRQ,isST"
P3 = ("float", 3)
DAILY_SCHEMA = {"date": "str", "code": "str", "open": P3, "high": P3, "low": P3, "close": P3,
                "preclose": P3, "volume": "int", "amount": "int", "turn": ("float", 4),
                "tradestatus": "int", "pctChg": ("float", 4), "peTTM": P3, "pbMRQ": P3,
                "isST": "int"}
INDEX_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
INDEX_SCHEMA = {"date": "str", "code": "str", "open": P3, "high": P3, "low": P3, "close": P3,
                "preclose": P3, "volume": "int", "amount": "int", "pctChg": ("float", 4)}
FACTOR_SCHEMA = {"code": "str", "dividOperateDate": "str", "foreAdjustFactor": ("float", 8),
                 "backAdjustFactor": ("float", 8), "adjustFactor": ("float", 8)}


# ------------------------------------------------------------------ baostock helpers

def _login(bs) -> bool:
    for i in range(5):
        with contextlib.redirect_stdout(io.StringIO()):
            lg = bs.login()
        if lg.error_code == "0":
            return True
        time.sleep(2 + 3 * i)
    return False


def _logout(bs) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            bs.logout()
        except Exception:
            pass


def _rows(rs):
    if rs.error_code != "0":
        raise RuntimeError(f"baostock {rs.error_code}: {rs.error_msg}")
    rows = []
    while (rs.error_code == "0") & rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"baostock {rs.error_code}: {rs.error_msg}")
    return rows, list(rs.fields)


def _df(rs) -> pd.DataFrame:
    rows, fields = _rows(rs)
    return pd.DataFrame(rows, columns=fields)


# worker side (runs in spawned processes) ----------------------------------------

def _w_init():
    import baostock as bs
    _login(bs)


def _w_task(task):
    kind, code, start, end = task
    import baostock as bs
    err = None
    for attempt in range(3):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                if kind == "bars":
                    rs = bs.query_history_k_data_plus(code, FIELDS, start_date=start, end_date=end,
                                                      frequency="d", adjustflag="3")
                else:
                    rs = bs.query_adjust_factor(code=code, start_date="1990-01-01", end_date=end)
                rows, fields = _rows(rs)
            return task, rows, fields, None
        except Exception as e:
            err = str(e)
            time.sleep(1 + 3 * attempt)
            _logout(bs)
            _login(bs)
    return task, None, None, err


# ------------------------------------------------------------------ main

def _needs_factor(df: pd.DataFrame) -> bool:
    """Ex-rights day inside the fetched rows: preclose differs from the previous row's close."""
    if len(df) < 2:
        return False
    close = df["close"].to_numpy(dtype=float)
    pre = df["preclose"].to_numpy(dtype=float)
    diff = np.abs(pre[1:] - close[:-1])
    return bool(np.nanmax(diff, initial=0) > 0.006)


def run(root: Path, mode: str, deadline: float) -> tuple[dict, bool]:
    """Returns (status, complete). complete=False means the time budget ran out mid-backfill."""
    st = Stage("a_share")
    complete = True
    try:
        import baostock as bs
        base = root / "a_share"
        a_start = "2025-06-01" if mode == "smoke" else C.A_START

        if not _login(bs):
            raise RuntimeError("baostock login failed")
        now_cst = datetime.now(timezone.utc) + timedelta(hours=8)
        cutoff = now_cst.date() if now_cst.hour >= 20 else now_cst.date() - timedelta(days=1)
        cal = _df(bs.query_trade_dates(start_date="2014-12-01", end_date=now_cst.strftime("%Y-%m-%d")))
        write_csv(cal, base / "meta" / "trade_dates.csv")
        trading = sorted(cal.loc[cal["is_trading_day"] == "1", "calendar_date"])
        end = max(d for d in trading if d <= cutoff.isoformat())
        st.info["end_date"] = end
        st.log(f"target end date {end}")

        basic = _df(bs.query_stock_basic())
        write_csv(basic, base / "meta" / "stock_basic.csv")
        try:
            write_csv(_df(bs.query_stock_industry()), base / "meta" / "industry.csv")
        except Exception as e:
            st.error(f"industry: {e}")

        idx = []
        for code in C.A_INDICES:
            try:
                idx.append(_df(bs.query_history_k_data_plus(code, INDEX_FIELDS, start_date=a_start,
                                                            end_date=end, frequency="d")))
            except Exception as e:
                st.error(f"index {code}: {e}")
        if idx:
            idf = normalize(pd.concat(idx, ignore_index=True), INDEX_SCHEMA)
            write_csv(idf.sort_values(["code", "date"]), base / "index_daily.csv.xz")
            st.info["index_rows"] = len(idf)
        _logout(bs)

        stocks = basic[(basic["type"] == "1") &
                       ((basic["outDate"] == "") | (basic["outDate"] >= a_start))].copy()
        if mode == "smoke":
            stocks = stocks[stocks["code"].isin(C.A_SMOKE_CODES)]
        stocks = stocks.sort_values(["status", "code"], ascending=[False, True])

        state_path = base / "meta" / "fetch_state.csv"
        state = load_state(state_path, ["code", "fetched_through", "factor_through"])
        sd = {r.code: [r.fetched_through, r.factor_through] for r in state.itertuples()}
        tasks = []
        for r in stocks.itertuples():
            stop = min(end, r.outDate) if r.outDate else end
            ft = sd.get(r.code, ["", ""])[0]
            if ft and ft >= stop:
                continue
            start = max(a_start, r.ipoDate or a_start)
            if ft:   # re-fetch a week of overlap so late-arriving rows self-heal
                start = max(start, (datetime.fromisoformat(ft) - timedelta(days=7)).strftime("%Y-%m-%d"))
            if start <= stop:
                tasks.append(("bars", r.code, start, stop))
        st.info["bar_tasks"] = len(tasks)
        st.log(f"{len(tasks)} stocks to fetch ({len(stocks)} in universe)")

        today_cst = now_cst.date()
        monthly_refresh = today_cst.weekday() == 5 and today_cst.day <= 7
        frames, factor_codes, done = [], set(), 0
        factor_frames, factor_done = [], []
        workers = 2 if mode == "smoke" else 6
        t_start = time.time()
        ctx = mp.get_context("spawn")
        with ctx.Pool(workers, initializer=_w_init) as pool:
            for task, rows, fields, err in pool.imap_unordered(_w_task, tasks, chunksize=1):
                code = task[1]
                if err:
                    st.error(f"bars {code}: {err}")
                else:
                    df = normalize(pd.DataFrame(rows, columns=fields), DAILY_SCHEMA)
                    if len(df):
                        frames.append(df)
                        if _needs_factor(df):
                            factor_codes.add(code)
                    sd.setdefault(code, ["", ""])[0] = task[3]
                    done += 1
                    if done % 250 == 0:
                        el = time.time() - t_start
                        st.log(f"bars {done}/{len(tasks)}  {el / done:.2f}s/stock")
                if time.time() > deadline:
                    complete = False
                    st.error(f"deadline: stopped after {done}/{len(tasks)} stocks")
                    pool.terminate()
                    break

            if complete:
                for code in stocks["code"]:
                    v = sd.get(code)
                    if v and v[0] and (not v[1] or monthly_refresh):
                        factor_codes.add(code)
                ftasks = [("factor", c, "", end) for c in sorted(factor_codes) if c in sd and sd[c][0]]
                st.info["factor_tasks"] = len(ftasks)
                for task, rows, fields, err in pool.imap_unordered(_w_task, ftasks, chunksize=1):
                    if err:
                        st.error(f"factor {task[1]}: {err}")
                    else:
                        if rows:
                            factor_frames.append(pd.DataFrame(rows, columns=fields))
                        factor_done.append(task[1])
                    if time.time() > deadline:
                        complete = False
                        st.error("deadline during factor refresh")
                        pool.terminate()
                        break

        st.info["stocks_done"] = done
        if done:
            st.info["sec_per_stock"] = round((time.time() - t_start) / max(done, 1), 2)
        if frames:
            allbars = pd.concat(frames, ignore_index=True)
            st.info["latest_bar"] = allbars["date"].max()
            st.log(f"writing {len(allbars):,} bar rows")
            st.info["rows_added"] = int(merge_partitioned(allbars, base / "daily", ["code", "date"],
                                                          "date", DAILY_SCHEMA))
            del allbars, frames
        if factor_done:
            fdf = (pd.concat(factor_frames, ignore_index=True) if factor_frames
                   else pd.DataFrame(columns=list(FACTOR_SCHEMA)))
            replace_rows(fdf, base / "adj_factor.csv.xz", "code", FACTOR_SCHEMA)
            for c in factor_done:
                sd[c][1] = end
            st.info["factors_refreshed"] = len(factor_done)
        save_state(pd.DataFrame([{"code": k, "fetched_through": v[0], "factor_through": v[1]}
                                 for k, v in sorted(sd.items())]), state_path)
        remaining = sum(1 for r in stocks.itertuples()
                        if not sd.get(r.code, [""])[0])
        st.info["stocks_never_fetched"] = remaining
        st.info["ok"] = done > 0 or not tasks
        st.info["progress_made"] = done > 0
    except Exception as e:
        st.crash(e)
        complete = False
    return st.result(), complete
