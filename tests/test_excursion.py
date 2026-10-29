from types import SimpleNamespace

import numpy as np

from jsq import excursion as ex


def _one(hi, lo, side=1, end=None):
    hi, lo = np.array([hi], float), np.array([lo], float)
    end = hi[0, -1] if end is None else end
    return ex.touches(hi, lo, [100.0], [side], [1.0], [end])


def test_first_touch_order_and_outcomes():
    # 多单 100 进，1R = 1 元：+0.6 → +1.2（先到 +1R），之后才跌到 -1.1
    t = _one([100.6, 101.2, 100.5], [99.8, 99.5, 98.9], end=99.0)
    assert t.attrs["H"] == 3
    assert (t["f0.5"][0], t["f1.0"][0], t["f1.5"][0]) == (0, 1, 3)   # 3 = 窗口内没到
    assert (t["a0.5"][0], t["a1.0"][0]) == (1, 2)
    assert ex.outcome(t, 1.0)[0] == 1.0          # 目标 1R 先到
    assert ex.outcome(t, 1.5)[0] == -1.0         # 目标 1.5R 没到，先止损
    assert abs(t["mfe_pre"][0] - 1.2) < 1e-9     # 止损前最多浮盈 1.2R
    f = ex._flags(t)
    assert f["right"][0] and not f["wrong"][0] and f["half"][0]


def test_same_bar_counts_as_loss_and_short_side():
    t = _one([101.5], [98.9])                    # 同一根 K 线两边都碰到 → 算先亏
    assert ex.outcome(t, 1.0)[0] == -1.0
    s = _one([100.3, 100.2], [99.4, 98.8], side=-1, end=99.0)   # 空单：价格往下是浮盈
    assert s["f0.5"][0] == 0 and s["f1.0"][0] == 1 and s["a1.0"][0] == 2
    assert abs(s["end"][0] - 1.0) < 1e-9


def test_time_exit_uses_window_close():
    t = _one([100.4, 100.3], [99.7, 99.8], end=100.2)
    assert abs(ex.outcome(t, 1.0)[0] - 0.2) < 1e-9   # 两边都没碰到，按窗口最后收盘 +0.2R 平


def test_random_direction_has_no_edge_but_oracle_does():
    rng = np.random.default_rng(0)
    n, H = 3000, 40
    steps = rng.normal(0, 0.3, (n, H))
    close = 100 + np.cumsum(steps, axis=1)
    hi, lo = close + 0.05, close - 0.05
    entry = np.full(n, 100.0)
    r = np.ones(n)
    rand = rng.choice([-1.0, 1.0], n)
    p = ex.profile(ex.touches(hi, lo, entry, rand, r, close[:, -1]),
                   ex.touches(hi, lo, entry, -rand, r, close[:, -1]), 0.0)
    assert abs(p["right"] - p["right_base"]) < 0.04 and abs(p["right_t"]) < 3
    assert abs(p["B1.0"]) < 0.05
    oracle = np.sign(close[:, -1] - 100)        # 偷看结果的“信号”：方向对的比例应明显高于对照
    q = ex.profile(ex.touches(hi, lo, entry, oracle, r, close[:, -1]),
                   ex.touches(hi, lo, entry, -oracle, r, close[:, -1]), 0.0)
    assert q["right"] > q["right_base"] + 0.2 and q["right_t"] > 5


def test_hourly_paths_start_after_signal_bar():
    o = np.arange(10, dtype=float)
    p = SimpleNamespace(o=o, h=o + 0.5, l=o - 0.5, c=o + 0.2)
    ev, entry, hi, lo, end = ex.hourly_paths(p, np.array([2, 8]), 3)
    assert list(ev) == [2]                       # 第 8 根之后不够 3 根，丢掉
    assert entry[0] == 3.0                       # 第 2 根收盘出信号，第 3 根开盘成交
    assert list(hi[0]) == [3.5, 4.5, 5.5] and end[0] == 5.2


def test_path_classes_are_exclusive_and_match_the_story():
    # 多单 100 进，1R = 1 元，窗口 4 根
    cases = {
        "trend": ([101.0, 102.5, 101.0, 100.0], [99.9, 100.5, 100.2, 99.5]),   # 先到 +2R
        "fake": ([100.9, 100.5, 99.0, 98.0], [100.1, 99.5, 97.9, 96.5]),       # +0.9R 后跌到 -2R、-3R
        "direct": ([100.3, 99.5, 99.0, 98.0], [99.5, 98.0, 97.5, 97.0]),       # 没到 +0.8R 就到 -2R
        "flat": ([100.7, 101.5, 100.5, 100.2], [99.4, 99.0, 99.2, 99.8]),      # ±2R 都没到
    }
    for want, (hi, lo) in cases.items():
        t = _one(hi, lo, end=lo[-1])
        f = ex.path_flags(t)
        got = [k for k in ("trend", "fake", "direct", "flat") if f[k][0]]
        assert got == [want], (want, got)
    t = _one(*cases["fake"], end=96.6)
    assert ex.path_flags(t)["fake3"][0]           # 先顺后一路跌到 -3R


def test_path_profile_baseline_is_mirror():
    t = _one([100.9, 100.5, 99.0, 98.0], [100.1, 99.5, 97.9, 96.5], end=97.0)
    o = _one([100.9, 100.5, 99.0, 98.0], [100.1, 99.5, 97.9, 96.5], side=-1, end=97.0)
    p = ex.path_profile(t, o, 0.0, ends={72: [-3.0]})
    assert p["p_fake"] == 1.0 and p["p_trend_base"] == 0.5    # 反方向是一路顺：随机猜方向一半一半
    assert p["end_le-2"] == 1.0 and p["end_le-2_base"] == 0.5
    assert p["hold72"] == -3.0 and p["hold72_up"] == 0.0
