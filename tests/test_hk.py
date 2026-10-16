import numpy as np
import pandas as pd

from jsq import hk


def test_remaining_gap_and_advice():
    # 竞价 -2%，合约已跌 3% -> 合约跌过头，剩余为正（合约该往回涨）
    rem = hk.remaining_gap(-0.02, -0.03)
    assert rem > 0 and "过头" in hk.advise_preopen(rem, -0.02)
    rem = hk.remaining_gap(-0.03, -0.01)
    assert rem < 0 and "做空" in hk.advise_preopen(rem, -0.03)
    assert "无信号" in hk.advise_open(0.001) and "做空" in hk.advise_open(0.005)


def _fake_day_frame():
    # 两个交易日：指数在 09:30 才跳到开盘价，合约在夜里提前走了一部分
    idx = pd.date_range("2026-08-03 00:00", "2026-08-04 23:59", freq="1min", tz="Asia/Hong_Kong")
    n = len(idx)
    hm = idx.hour * 60 + idx.minute
    day2 = idx.day == 4
    index = np.where(day2 & (hm >= 570), 102.0, 100.0) + np.where((hm >= 570) & (hm < 960), np.sin(np.arange(n)) * 0.2, 0)
    perp = np.where(day2 & (hm >= 1), 101.0, 100.0)
    perp = np.where(day2 & (hm >= 570), 102.0, perp) + np.where((hm >= 570) & (hm < 960), np.sin(np.arange(n)) * 0.2, 0)
    df = pd.DataFrame({"open": perp, "high": perp, "low": perp, "close": perp, "volume": 1.0, "quote_volume": 1.0,
                       "index": index}, index=idx.tz_convert("UTC"))
    df.attrs["symbol"] = "TESTUSDT"
    return df


def test_daily_table_prepricing():
    t = hk.daily_table(_fake_day_frame())
    assert len(t) == 1
    r = t.iloc[0]
    assert abs(r["gap"] - 0.02) < 0.005          # 正股跳空约 +2%
    assert abs(r["perp_to_0929"] - 0.01) < 0.005  # 合约开盘前已走约 +1%
    assert r["resid_0929"] > 0                    # 还剩约 1% 没反映
