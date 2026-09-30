import numpy as np
import pandas as pd
import pytest

from ashare_lab.core import backtest as B
from ashare_lab.core import regimes as G
from ashare_lab.core import returns as R
from ashare_lab.core import stats
from ashare_lab.core.events import condition_events, crossing_events
from ashare_lab.core.eventstudy import event_study, lookup
from ashare_lab.core.zigzag import filter_short_legs, legs, zigzag


def _dates(n):
    return pd.bdate_range("2020-01-01", periods=n)


# ------------------------------------------------------------------ returns
def test_fwd_return_alignment():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=_dates(5))
    assert R.fwd_return(s, 1, 0).iloc[0] == pytest.approx(1.0)       # 1 → 2
    assert R.fwd_return(s, 1, 1).iloc[0] == pytest.approx(0.5)       # 2 → 3（次日入场）
    assert np.isnan(R.fwd_return(s, 2, 1).iloc[2])                   # 超出样本
    assert R.past_return(s, 2).iloc[2] == pytest.approx(2.0)


def test_fwd_min_return_window_excludes_entry_day():
    s = pd.Series([10.0, 9.0, 12.0, 8.0, 11.0], index=_dates(5))
    assert R.fwd_min_return(s, 2, 0).iloc[0] == pytest.approx(-0.1)  # min(9, 12)/10 - 1
    assert R.fwd_min_return(s, 1, 1).iloc[0] == pytest.approx(0.0)   # 入场 9，次日 12，不亏


def test_rolling_percentile_has_no_lookahead():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(size=300), index=_dates(300))
    p1 = R.rolling_percentile(s, 100, 50)
    s2 = s.copy()
    s2.iloc[200:] = 1e6  # 改动未来
    p2 = R.rolling_percentile(s2, 100, 50)
    pd.testing.assert_series_equal(p1.iloc[:200], p2.iloc[:200])
    assert p2.iloc[250] == pytest.approx(1.0)


def test_index_from_returns_uses_lagged_weights():
    idx = _dates(3)
    rets = pd.DataFrame({"a": [0.0, 0.10, 0.0], "b": [0.0, -0.10, 0.0]}, index=idx)
    w = pd.DataFrame({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 1.0]}, index=idx)
    out = R.index_from_returns(rets, w, base=1.0)
    # 第 2 天用第 1 天的权重（全在 a 上），所以涨 10%
    assert out.iloc[1] == pytest.approx(1.10)


# ------------------------------------------------------------------ zigzag
def test_zigzag_finds_alternating_pivots_and_confirm_day():
    path = np.r_[np.linspace(100, 150, 51), np.linspace(150, 90, 61)[1:], np.linspace(90, 117, 28)[1:]]
    s = pd.Series(path, index=_dates(len(path)))
    piv = zigzag(s, 0.2)
    assert list(piv["kind"]) == ["trough", "peak", "trough", "peak"]
    assert piv.iloc[1]["pos"] == 50
    assert piv.iloc[1]["value"] == pytest.approx(150)
    # 峰值 150 回撤 1-1/1.2 ≈ 16.7% 才确认（对数对称阈值）
    cp = piv.iloc[1]["confirm_pos"]
    assert np.log(150 / path[cp]) >= np.log(1.2) - 1e-12
    assert np.log(150 / path[cp - 1]) < np.log(1.2) + 1e-9
    assert bool(piv.iloc[-1]["confirmed"]) is False
    lg = legs(piv)
    assert list(lg["direction"]) == ["up", "down", "up"]


def test_filter_short_legs_merges_noise():
    path = np.r_[np.linspace(100, 200, 101), [180, 170, 190, 205], np.linspace(205, 120, 80)]
    s = pd.Series(path, index=_dates(len(path)))
    piv = zigzag(s, 0.05)
    filt = filter_short_legs(piv, s, 20)
    peaks = filt[filt["kind"] == "peak"]
    assert len(peaks) == 1
    assert peaks.iloc[0]["value"] == pytest.approx(205)


# ------------------------------------------------------------------ events
def test_crossing_events_rearm_and_gap():
    s = pd.Series([0.1, 0.35, 0.36, 0.32, 0.36, 0.2, 0.31, 0.1, 0.1, 0.4], index=_dates(10))
    ev = crossing_events(s, 0.30, rearm=0.25, min_gap=0)
    # 0.32 没跌破 0.25，不重新计数；0.2 之后的 0.31 算第二次；0.1 之后 0.4 第三次
    assert list(ev) == [s.index[1], s.index[6], s.index[9]]
    assert list(crossing_events(s, 0.30, rearm=0.25, min_gap=5)) == [s.index[1], s.index[6]]
    # 间隔不足 min_gap 的穿越视为同一事件的延续，并顺延“上次事件”时间
    assert list(crossing_events(s, 0.30, rearm=0.25, min_gap=6)) == [s.index[1]]


def test_crossing_events_ignores_start_above_threshold():
    s = pd.Series([0.5, 0.5, 0.1, 0.5], index=_dates(4))
    assert list(crossing_events(s, 0.3)) == [s.index[3]]


def test_condition_events_declusters_runs():
    c = pd.Series([True, True, False, True, False, False, False, True], index=_dates(8))
    assert list(condition_events(c, 3)) == [c.index[0], c.index[7]]


# ------------------------------------------------------------------ stats
def test_bh_adjust_matches_reference():
    q = stats.bh_adjust([0.01, 0.04, 0.03, 0.20, np.nan])
    assert q[0] == pytest.approx(0.04)
    assert q[1] == pytest.approx(0.0533333, rel=1e-4)
    assert q[2] == pytest.approx(0.0533333, rel=1e-4)
    assert q[3] == pytest.approx(0.20)
    assert np.isnan(q[4])


def test_evidence_grade_rules():
    assert stats.evidence_grade(3, 0.001, True) == "D"
    assert stats.evidence_grade(25, 0.01, True) == "A"
    assert stats.evidence_grade(25, 0.01, False) == "C"
    assert stats.evidence_grade(12, 0.08, True) == "B"
    assert stats.evidence_grade(8, 0.001, True) == "C"


def test_newey_west_recovers_slope():
    rng = np.random.default_rng(1)
    x = rng.normal(size=2000)
    e = np.convolve(rng.normal(size=2020), np.ones(20) / 20, mode="valid")[:2000]
    y = 0.5 * x + e
    out = stats.newey_west(y, x, lags=20)
    assert out["beta"] == pytest.approx(0.5, abs=0.05)
    assert out["t"] > 5


def test_date_clusters_groups_nearby_events():
    cal = _dates(200)
    d = [cal[10], cal[15], cal[100], cal[12], cal[190]]
    cl = stats.date_clusters(d, 20, cal)
    assert cl[0] == cl[1] == cl[3]
    assert len(set(cl)) == 3


def test_shift_test_detects_real_effect_and_not_noise():
    rng = np.random.default_rng(2)
    n = 1500
    idx = _dates(n)
    vals = pd.DataFrame({"a": rng.normal(size=n)}, index=idx)
    ev_pos = np.arange(50, n - 50, 60)
    events = pd.DataFrame({"date": idx[ev_pos], "key": "a"})
    p_null = stats.shift_test(vals, events, n_perm=1000, rng=rng)["p"]
    assert p_null > 0.05
    vals2 = vals.copy()
    vals2.iloc[ev_pos, 0] += 1.0
    assert stats.shift_test(vals2, events, n_perm=1000, rng=rng)["p"] < 0.01


def test_cluster_bootstrap_diff():
    rng = np.random.default_rng(3)
    g = np.r_[np.ones(40, bool), np.zeros(40, bool)]
    y = np.r_[rng.random(40) < 0.8, rng.random(40) < 0.2].astype(float)
    cl = np.arange(80)
    out = stats.cluster_bootstrap_diff(y, g, cl, rng=rng)
    assert out["diff"] > 0.3 and out["p"] < 0.01


def test_event_study_basic_columns_and_direction():
    rng = np.random.default_rng(4)
    n = 800
    idx = _dates(n)
    vals = pd.DataFrame(rng.normal(0, 0.01, size=(n, 2)), index=idx, columns=["a", "b"])
    pos = np.arange(30, n - 30, 40)
    vals.iloc[pos, 0] += 0.05
    events = pd.DataFrame({"date": idx[pos], "key": "a"})
    t = event_study(events, {"m": vals}, None, idx[n // 2], 500, 500, rng)
    row = t.iloc[0]
    assert row["n"] == len(pos)
    assert row["差值"] > 0.04
    assert row["p值"] < 0.01
    assert bool(row["两段同向"])
    assert np.allclose(lookup(vals, events), vals["a"].to_numpy()[pos])


# ------------------------------------------------------------------ backtest
def test_backtest_respects_entry_lag_and_costs():
    idx = _dates(6)
    r = pd.DataFrame({"x": [0.0, 0.01, 0.02, 0.03, 0.04, 0.05]}, index=idx)
    w = pd.DataFrame({"x": [1.0] * 6}, index=idx)
    out0 = B.run_weights(w, r, entry_lag=0, cost_bps=0)
    assert out0.iloc[0] == 0 and out0.iloc[1] == pytest.approx(0.01)
    out1 = B.run_weights(w, r, entry_lag=1, cost_bps=10)
    assert out1.iloc[1] == 0
    assert out1.iloc[2] == pytest.approx(0.02 - 0.001)   # 建仓日扣一次单边成本
    assert out1.iloc[3] == pytest.approx(0.03)


def test_top_k_weights_and_hold_every():
    idx = _dates(4)
    score = pd.DataFrame({"a": [3, 1, 3, 1], "b": [2, 2, 2, 2], "c": [1, 3, 1, 3]}, index=idx, dtype=float)
    w = B.top_k_weights(score, 1)
    assert w.iloc[0]["a"] == 1.0 and w.iloc[1]["c"] == 1.0
    h = B.hold_every(w, 2)
    assert h.iloc[1]["a"] == 1.0  # 第二天不调仓


def test_perf_stats_known_values():
    r = pd.Series([0.01] * 244)
    s = B.perf_stats(r)
    assert s["年化收益"] == pytest.approx(1.01 ** 244 - 1)
    assert s["最大回撤"] == 0


# ------------------------------------------------------------------ regimes
def test_regime_ma_and_persist():
    up = pd.Series(np.linspace(100, 200, 400), index=_dates(400))
    lab = G.regime_ma(up, 250, 20)
    assert lab.iloc[-1] == G.BULL and pd.isna(lab.iloc[100])
    raw = pd.Series([G.BULL] * 5 + [G.BEAR] * 2 + [G.BULL] * 3 + [G.BEAR] * 4, index=_dates(14))
    sm = G.persist(raw, 3)
    assert list(sm.iloc[5:10]) == [G.BULL] * 5            # 两天的熊市是噪音
    assert sm.iloc[12] == G.BEAR                           # 连续 3 天才切换
    tail = pd.Series([G.BULL, G.BULL, np.nan], index=_dates(3), dtype=object)
    assert pd.isna(G.persist(tail, 2).iloc[-1])            # 缺失不向前填充
