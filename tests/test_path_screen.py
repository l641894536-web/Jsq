import numpy as np
import pandas as pd

from jsq import live_paths as lp
from jsq import path_screen as ps
from jsq.data import load_frame
from jsq.synthetic import make_dataset


def _frames(tmp_path):
    syms = make_dataset(tmp_path, "1h", days=240)
    return {s: load_frame(s, "1h", tmp_path) for s in syms}


def test_screen_group_runs_and_reports_oos_paths(tmp_path):
    res = ps.screen_group(_frames(tmp_path), "加密", ["donchian", "bb_break"], min_events=10)
    assert len(res) and {"path_t", "trend", "trend_b", "bracket", "picks"} <= set(res.columns)
    assert ((res["trend"] >= 0) & (res["trend"] <= 1)).all()


def _breakout_frame(rally: float):
    """72 根横盘后向上突破，然后走 rally（每根）——用来检查虚拟单的止损 / 止盈 / 到期。"""
    idx = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    rng = np.random.default_rng(1)
    c = np.r_[100 + rng.normal(0, 0.2, 100), 101.5 + np.cumsum(np.full(100, rally))]
    df = pd.DataFrame({"open": np.r_[c[0], c[:-1]], "high": c + 0.3, "low": c - 0.3, "close": c,
                       "funding_paid": 0.0}, index=idx)
    df["open"] = np.minimum(np.maximum(df["open"], df["low"]), df["high"])
    df.attrs["symbol"], df.attrs["bar_hours"] = "TEST", 1.0
    return df


def test_virtual_trades_take_profit_and_no_target():
    cfg = dict(lp.SIGNALS[0])
    up = lp.virtual_trades(_breakout_frame(0.2), cfg)
    first = up.iloc[0]
    assert first["side"] == 1 and first["status"] == "止盈" and first["ret_R"] > 2.5
    cfg["tp_R"] = None                                # 不设止盈：一直拿到 72 小时到期或数据结束
    t = lp.virtual_trades(_breakout_frame(0.2), cfg).iloc[0]
    assert t["status"] in ("到期", "持仓中") and np.isnan(t["target"])
    down = lp.virtual_trades(_breakout_frame(-0.2), dict(lp.SIGNALS[0]))
    assert (down["status"] == "止损").any()


def test_triggers_for_both_signal_types():
    df = _breakout_frame(0.0)
    t = lp.triggers(df, lp.SIGNALS[0])
    assert t["up"] >= df["high"].iloc[-72:].max() - 1e-9 and t["down"] <= df["low"].iloc[-72:].min() + 1e-9
    b = lp.triggers(_breakout_frame(0.2), lp.SIGNALS[1])   # 布林带：均线 ± 2.5 倍标准差，回到均线结束
    assert b["up"] > b["long_exit"] > b["down"] and "regime" in b and "ok" in b
