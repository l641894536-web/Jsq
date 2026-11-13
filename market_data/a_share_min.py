"""A-share 5-minute bars from baostock for a small watchlist (config.A_MIN_CODES).

Stored UNADJUSTED under a_share/min5/YYYY/YYYY-MM.csv.xz with columns date,time,code,open,high,low,close,volume,amount
(`time` is baostock's bar END time, e.g. 20260112093500000 = the 09:30-09:35 bar). Intraday ratios need no
adjustment; for gaps use the daily table's preclose. State: a_share/min5_state.csv (code, fetched_from, fetched_through).
Fetched with a pool of logged-in baostock workers (minute queries are slow); everything is merged once at the end.
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import config as C
from .a_share import _login, _logout, _rows
from .common import Stage, load_state, merge_partitioned, save_state

FIELDS = "date,time,code,open,high,low,close,volume,amount"
P4 = ("float", 4)
SCHEMA = {"date": "str", "time": "str", "code": "str", "open": P4, "high": P4, "low": P4, "close": P4,
          "volume": "int", "amount": "int"}


def _chunks(start: str, end: str, days: int = 92):
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    while s <= e:
        t = min(e, s + timedelta(days=days - 1))
        yield s.strftime("%Y-%m-%d"), t.strftime("%Y-%m-%d")
        s = t + timedelta(days=1)


def _w_init():
    import baostock as bs
    _login(bs)


def _w_task(task):
    code, s_, e_ = task
    import baostock as bs
    err = None
    for attempt in range(3):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rs = bs.query_history_k_data_plus(code, FIELDS, start_date=s_, end_date=e_, frequency="5", adjustflag="3")
                rows, fields = _rows(rs)
            return task, rows, fields, None
        except Exception as e:
            err = str(e)
            time.sleep(1 + 3 * attempt)
            _logout(bs)
            _login(bs)
    return task, None, None, err


def run(root: Path, mode: str, deadline: float) -> dict:
    st = Stage("a_share_min")
    try:
        base = root / "a_share" / "min5"
        state_p = root / "a_share" / "min5_state.csv"
        sd = load_state(state_p, ["code", "fetched_from", "fetched_through"]).set_index("code")
        codes = C.A_MIN_CODES[:2] if mode == "smoke" else C.A_MIN_CODES
        start0 = "2026-10-01" if mode == "smoke" else C.A_MIN_START
        now_cst = datetime.now(timezone.utc) + timedelta(hours=8)
        end = (now_cst.date() if now_cst.hour >= 18 else now_cst.date() - timedelta(days=1)).isoformat()
        tasks, need = [], {}
        for code in codes:
            ff = sd.loc[code, "fetched_from"] if code in sd.index else ""
            ft = sd.loc[code, "fetched_through"] if code in sd.index else ""
            spans = []
            if not ft:
                spans.append((start0, end))
            else:
                if ff and start0 < ff:
                    spans.append((start0, (datetime.fromisoformat(ff) - timedelta(days=1)).strftime("%Y-%m-%d")))
                spans.append(((datetime.fromisoformat(ft) - timedelta(days=5)).strftime("%Y-%m-%d"), end))
            for a, b in spans:
                for c_ in _chunks(a, b):
                    tasks.append((code,) + c_)
                    need[code] = need.get(code, 0) + 1
        st.log(f"{len(tasks)} chunks for {len(need)} codes, through {end}")
        frames, got, failed, rows_n = [], {}, set(), 0
        t0 = time.time()
        ctx = mp.get_context("spawn")
        with ctx.Pool(1 if mode == "smoke" else 6, initializer=_w_init) as pool:
            for i, (task, rows, fields, err) in enumerate(pool.imap_unordered(_w_task, tasks, chunksize=1), 1):
                if err:
                    st.error(f"{task}: {err}")
                    failed.add(task[0])
                else:
                    got[task[0]] = got.get(task[0], 0) + 1
                    if rows:
                        frames.append(pd.DataFrame(rows, columns=fields)); rows_n += len(rows)
                if i % 20 == 0:
                    st.log(f"{i}/{len(tasks)} chunks, {rows_n:,} rows, {(time.time() - t0) / i:.1f}s/chunk")
                if time.time() > deadline:
                    st.error(f"deadline after {i}/{len(tasks)} chunks")
                    pool.terminate()
                    break
        added = 0
        if frames:
            allm = pd.concat(frames, ignore_index=True)
            st.log(f"writing {len(allm):,} rows")
            added = merge_partitioned(allm, base, ["code", "time"], "date", SCHEMA)
            have = set(allm["code"])
        else:
            have = set()
        for code, n in need.items():
            if got.get(code, 0) == n and code not in failed:
                ff = sd.loc[code, "fetched_from"] if code in sd.index else ""
                if code in have or ff:
                    sd.loc[code, "fetched_from"] = min([x for x in [ff, start0] if x])
                    sd.loc[code, "fetched_through"] = end
                else:
                    st.log(f"{code}: no minute data (not covered by baostock?)")
        save_state(sd.reset_index(), state_p)
        st.info.update(ok=True, rows_added=int(added), rows_fetched=rows_n, chunks=len(tasks), codes_with_data=sorted(have), end=end,
                       sec_per_chunk=round((time.time() - t0) / max(len(tasks), 1), 1))
    except Exception as e:
        st.crash(e)
    return st.result()
