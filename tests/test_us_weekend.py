import numpy as np
import pandas as pd

from jsq import us_weekend as uw


def _frame(index_jump: float):
    """美东 周五 19:50 到 周一 16:05：合约周末从 100 涨到 102，指数周末不动，周日 20:00 跳到 100*(1+index_jump)。"""
    et = pd.date_range("2026-08-07 19:50", "2026-08-10 16:05", freq="min", tz=uw.TZ)
    n = len(et)
    sun20 = et.get_loc(pd.Timestamp("2026-08-09 20:00", tz=uw.TZ))
    perp = np.full(n, 100.0)
    fri20 = et.get_loc(pd.Timestamp("2026-08-07 20:00", tz=uw.TZ))
    perp[fri20:sun20] = np.linspace(100, 102, sun20 - fri20)
    perp[sun20:] = 101.0                         # 开盘后回落到 101
    index = np.full(n, 100.0)
    index[sun20:] = 100 * (1 + index_jump)
    df = pd.DataFrame({"close": perp, "index": index}, index=et.tz_convert("UTC"))
    df.attrs["symbol"] = "TEST"
    return df


def test_weekend_move_gap_and_after():
    t = uw.weekend_table(_frame(0.01))
    assert len(t) == 1
    r = t.iloc[0]
    assert abs(r["W"] - 0.02) < 1e-3              # 周末合约涨 2%
    assert abs(r["J"] - 0.01) < 1e-9              # 正股实际只跳 1%
    assert r["周日20:05"] < 0 and abs(r["周一15:59"] - (101 / 102 - 1)) < 1e-6
    rules = uw.rules(t, ths=(0.01,))
    fade = rules[(rules["rule"] == "周末合约涨跌 >1.0%：反向") & (rules["exit"] == "周日20:05")].iloc[0]
    assert fade["mean"] > 0                       # 走过头的周末，反向做赚钱


def test_holiday_weekend_skipped():
    assert uw.weekend_table(_frame(0.0)).empty   # 周日 20:05 指数没动（周一假期）→ 跳过
