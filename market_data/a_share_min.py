"""A-share 5-minute bars from baostock for a small watchlist (config.A_MIN_CODES).

Stored UNADJUSTED under a_share/min5/YYYY/YYYY-MM.csv.xz with columns date,time,code,open,high,low,close,volume,amount
(`time` is baostock's bar END time, e.g. 20260112093500000 = the 09:30-09:35 bar). Intraday ratios need no
adjustment; for gaps use the daily table's preclose. State: a_share/min5_state.csv (code, fetched_from, fetched_through).
"""
from __future__ import annotations

import contextlib
import io
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import config as C
from .a_share import _login, _logout, _rows
from .common import Stage, load_state, merge_partitioned, save_state

FIELDS = "date,time,code,open,high,low,close,volume,amount"
P3 = ("float", 4)
SCHEMA = {"date": "str", "time": "str", "code": "str", "open": P3, "high": P3, "low": P3, "close": P3,
          "volume": "int", "amount": "int"}


def _chunks(start: str, end: str, days: int = 180):
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    while s <= e:
        t = min(e, s + timedelta(days=days - 1))
        yield s.strftime("%Y-%m-%d"), t.strftime("%Y-%m-%d")
        s = t + timedelta(days=1)


def run(root: Path, mode: str, deadline: float) -> dict:
    st = Stage("a_share_min")
    try:
        import baostock as bs
        base = root / "a_share" / "min5"
        state_p = root / "a_share" / "min5_state.csv"
        sd = load_state(state_p, ["code", "fetched_from", "fetched_through"]).set_index("code")
        codes = C.A_MIN_CODES[:2] if mode == "smoke" else C.A_MIN_CODES
        start0 = "2026-10-01" if mode == "smoke" else C.A_MIN_START
        now_cst = datetime.now(timezone.utc) + timedelta(hours=8)
        end = (now_cst.date() if now_cst.hour >= 18 else now_cst.date() - timedelta(days=1)).isoformat()
        if not _login(bs):
            raise RuntimeError("baostock login failed")
        added, done = 0, 0
        for code in codes:
            if time.time() > deadline:
                st.log("time budget reached")
                break
            ff = sd.loc[code, "fetched_from"] if code in sd.index else ""
            ft = sd.loc[code, "fetched_through"] if code in sd.index else ""
            spans = []
            if not ft or (ff and start0 < ff):
                spans.append((start0, (datetime.fromisoformat(ff) - timedelta(days=1)).strftime("%Y-%m-%d") if ff else end))
            if ft:
                spans.append(((datetime.fromisoformat(ft) - timedelta(days=5)).strftime("%Y-%m-%d"), end))
            got_any = False
            for a, b in spans:
                for s_, e_ in _chunks(a, b):
                    if time.time() > deadline:
                        break
                    rows = None
                    for attempt in range(3):
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                rs = bs.query_history_k_data_plus(code, FIELDS, start_date=s_, end_date=e_, frequency="5", adjustflag="3")
                                rows, fields = _rows(rs)
                            break
                        except Exception as e:
                            if attempt == 2:
                                st.error(f"{code} {s_}~{e_}: {e}")
                            time.sleep(1 + 2 * attempt); _logout(bs); _login(bs)
                    if rows:
                        df = pd.DataFrame(rows, columns=fields)
                        added += merge_partitioned(df, base, ["code", "time"], "date", SCHEMA)
                        got_any = True
            if got_any or ft:
                sd.loc[code, "fetched_from"] = min([x for x in [ff, start0] if x]) if got_any else ff
                sd.loc[code, "fetched_through"] = end
                done += 1
            else:
                st.log(f"{code}: no minute data (ETF/index not covered by baostock?)")
        _logout(bs)
        save_state(sd.reset_index(), state_p)
        st.info.update(ok=True, rows_added=added, codes_done=done, codes=len(codes), end=end)
    except Exception as e:
        st.crash(e)
    return st.result()
