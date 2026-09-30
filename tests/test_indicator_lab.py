"""指标实验室：面板口径、指标实现、横截面统计与回测记账的单元测试。"""

import numpy as np
import pandas as pd
import scipy.stats as sps

from indicator_lab import indicators as I
from indicator_lab.panel import Panel, board_limit
from indicator_lab.stats import nw_t, plateau, reality_check
from indicator_lab.xsec import backtest_rows, row_top_threshold, spearman_rows


def tiny_panel(C: np.ndarray, O: np.ndarray | None = None, limit: float = 0.10) -> Panel:
    n, m = C.shape
    C = C.astype(np.float32)
    O = C.copy() if O is None else O.astype(np.float32)
    H = np.fmax(O, C) * 1.01
    L = np.fmin(O, C) * 0.99
    V = np.ones_like(C) * 1e6
    return Panel(pd.bdate_range("2020-01-01", periods=n), [f"{600000 + j}" for j in range(m)], O, H.astype(np.float32),
                 L.astype(np.float32), C, V, V * C, np.full((n, m), limit, np.float32), np.ones((n, m), bool),
                 np.zeros((n, m), np.int8), np.array([""] * m, dtype=object),
                 np.cumsum(np.isfinite(C), 0).astype(np.int32))


def test_board_limit():
    d = pd.DatetimeIndex(["2020-08-21", "2020-08-24"])
    assert list(board_limit("600000", d)) == [np.float32(0.1)] * 2
    assert np.allclose(board_limit("300750", d), [0.1, 0.2])
    assert np.allclose(board_limit("688001", d), 0.2)
    assert np.allclose(board_limit("830799", d), 0.3)


def test_label_and_exit_delay():
    C = np.array([[10.0], [10.0], [10.0], [10.0], [10.0], [10.0]])
    O = np.array([[10.0], [10.0], [11.0], [9.0], [9.5], [12.0]])  # 第3行开盘 9.0 = 跌停（相对前收 10）
    P = tiny_panel(C, O)
    y = P.label(1)
    assert np.isclose(y[0, 0], 11 / 10 - 1)       # t=0：t+1 开盘 10 买，t+2 开盘 11 卖
    assert np.isclose(y[1, 0], 9 / 11 - 1)
    price, delayed = P.exit_table(max_delay=5, tol=0.005)
    assert delayed[3, 0] and np.isclose(price[3, 0], 9.5)   # 跌停顺延到下一天开盘
    assert not delayed[2, 0] and np.isclose(price[2, 0], 11.0)
    r = P.trade_return(1, 5, 0.005)
    assert np.isclose(r[1, 0], 9.5 / 11 - 1)


def test_limit_hits_and_eligibility():
    C = np.array([[10.0, 10.0], [11.0, 10.0], [11.0, 10.0]])
    O = np.array([[10.0, 10.0], [10.5, 10.0], [12.1, 10.0]])
    P = tiny_panel(C, O)
    P.H[1, 0] = 11.0                                   # 收在最高 = 涨停收盘
    hits = P.limit_hits(0.005)
    assert hits["up_close"][1, 0] and not hits["up_close"][1, 1]
    assert hits["open_up"][2, 0]
    E = P.eligible(1, 0.005)
    assert not E[1, 0] and E[1, 1]                      # 次日开盘涨停 → 买不进，不可入选


def test_indicator_basics():
    n = 300
    C = np.column_stack([np.linspace(10, 20, n), np.full(n, 10.0), 10 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.02, n)))])
    P = tiny_panel(C)
    bias = I.compute("bias_5", P)
    assert np.allclose(bias[10:, 1], 0, atol=1e-6)
    rsi = I.compute("rsi_14", P)
    assert np.allclose(rsi[50:, 0], 100, atol=1e-3)     # 单边上涨 → RSI=100
    k = I.compute("kdj_k", P)
    assert np.nanmin(k[:, 2]) >= 0 and np.nanmax(k[:, 2]) <= 100
    r20 = I.compute("ret_20", P)
    assert np.isclose(r20[100, 0], C[100, 0] / C[80, 0] - 1, rtol=1e-5)
    m12 = I.compute("mom_12_1", P)
    assert np.isclose(m12[299, 2], C[279, 2] / C[49, 2] - 1, rtol=1e-4)
    for name in I.REGISTRY:
        a = I.compute(name, P)
        assert a.shape == C.shape and a.dtype == np.float32, name
    assert len(I.REGISTRY) == 74


def test_spearman_rows_matches_scipy_with_ties():
    rng = np.random.default_rng(1)
    s = rng.integers(0, 5, (20, 80)).astype(float)
    y = s * 0.3 + rng.normal(size=(20, 80))
    y[:, :5] = np.nan
    mask = rng.random((20, 80)) > 0.1
    ic, *_ = spearman_rows(s, y, mask, min_n=10)
    for t in range(20):
        ok = mask[t] & np.isfinite(y[t])
        assert np.isclose(ic[t], sps.spearmanr(s[t, ok], y[t, ok]).statistic)


def test_top_threshold_and_backtest_accounting():
    x = np.array([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10.0]])
    thr = row_top_threshold(x, 0.9)
    assert thr[0] == 9                                  # 90% 分位取值；“>9” 这一档恰好 10%
    n, m = 4, 10
    sd = np.tile(np.arange(m, dtype=float), (n, 1))
    E = np.ones((n, m), bool)
    R = np.tile(np.linspace(0, 0.09, m), (n, 1))
    bt = backtest_rows(sd, False, E, E, np.zeros((n, m), bool), R, np.zeros((n, m), bool), h=1, top_q=0.1)
    assert np.allclose(bt["port"], 0.09)
    assert np.allclose(bt["bench"], R[0].mean())
    assert bt["turnover"][0] == 1 and np.allclose(bt["turnover"][1:], 0)


def test_stats_helpers():
    x = np.random.default_rng(2).normal(0.1, 1, 2000)
    r = nw_t(x, 5)
    assert 2 < r["t"] < 7
    tv = {"a": 5.0, "b": 3.0, "c": -1.0}
    ok = plateau(tv, ["a", "b", "c"], 0.5)
    assert ok["a"] and not ok["b"] and not ok["c"]
    X = np.random.default_rng(3).normal(0, 1, (500, 6))
    X[:, 0] += 0.4
    se = X.std(0) / np.sqrt(500)
    p = reality_check(X, se, 200, 10, seed=0)
    assert p[0] < 0.01 and np.all(p[1:] > 0.05)


def test_synthetic_power_and_null():
    from indicator_lab import runner as R
    from indicator_lab.synthetic import synthetic_panel
    cfg = R.load_cfg("config/indicators.toml")
    cfg["trade"]["horizons"] = [5]
    P = synthetic_panel(n_stocks=300, seed=7, plant=0.1)
    daily, ctx = R.run_signals(P, cfg, "dv", only=["ret_5", "log_amount_20"], log=lambda m: None)
    s = R.summarize(daily, ctx, cfg)
    val = s[s.split == "validation"].set_index("signal")
    assert val.loc["ret_5", "ic_t"] < -5 and val.loc["ret_5", "direction"] == -1
    assert val.loc["ret_5", "ann_gross"] > 0
    assert abs(val.loc["log_amount_20", "ic_t"]) < 3


def test_top_selection_discrete_signal():
    n, m = 2, 100
    E = np.ones((n, m), bool)
    sd = np.zeros((n, m))
    sd[:, :3] = 1.0                                     # 只有 3% 的股票为 1（如“创250日新高”）
    R = np.zeros((n, m))
    R[:, :3] = 0.05
    bt = backtest_rows(sd, False, E, E, np.zeros((n, m), bool), R, np.zeros((n, m), bool), h=1, top_q=0.1)
    assert np.allclose(bt["n_hold"], 3) and np.allclose(bt["port"], 0.05)


def test_oos_verdict_rules():
    from indicator_lab.oos import verdict
    rows = []
    for k, (n, m, lo, hi) in {"I1": (300, 0.05, -0.01, 0.1), "I2": (300, -0.05, -0.08, -0.01), "I3": (100, 0.1, 0, 0.2)}.items():
        rows += [{"规则": k, "区间": "验证集", "交易日": 1000, "年化超额(净)": 0.02},
                 {"规则": k, "区间": "测试集", "交易日": 800, "年化超额(净)": 0.02},
                 {"规则": k, "区间": "样本外", "交易日": n, "年化超额(净)": m, "90%CI下限": lo, "90%CI上限": hi}]
    v = verdict(pd.DataFrame(rows)).set_index("规则")["判定"]
    assert v["I1"] == "维持" and v["I2"] == "失效" and v["I3"].startswith("样本外 100")
