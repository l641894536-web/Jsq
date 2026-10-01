import numpy as np
import pandas as pd
import pytest

from jsq import backtest as bt
from jsq.analysis import predictive_power
from jsq.config import BacktestConfig
from jsq.data import load_frame
from jsq.optimize import evaluate_symbol
from jsq.strategies import STRATEGIES, get_strategies
from jsq.synthetic import make_dataset


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    syms = make_dataset(d, "1h", days=200)
    return load_frame(syms[1], "1h", d)


def _prep(o, h=None, l=None, c=None, fund=None, atr=1.0):
    o = np.asarray(o, float)
    n = len(o)
    c = o.copy() if c is None else np.asarray(c, float)
    h = np.maximum(o, c) if h is None else np.asarray(h, float)
    l = np.minimum(o, c) if l is None else np.asarray(l, float)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return bt.Prepared(idx, o, h, l, c, np.full(n, atr), np.zeros(n) if fund is None else np.asarray(fund, float), 1.0)


def test_signal_executes_next_open():
    p = _prep([100, 101, 102, 103, 104, 105])
    sig = np.array([0, 1, 1, 0, 0, 0])
    r = bt.run(p, sig, cost=0)
    t = r.trades.iloc[0]
    assert (t.entry_i, t.exit_i) == (2, 4)          # 第1根收盘发信号 -> 第2根开盘进; 第3根收盘平仓信号 -> 第4根开盘出
    assert t.ret == pytest.approx(104 / 102 - 1)
    assert r.equity[-1] == pytest.approx(104 / 102)


def test_costs_and_short():
    p = _prep([100, 100, 90, 80])
    r = bt.run(p, np.array([-1, -1, 0, 0]), cost=0.001)
    t = r.trades.iloc[0]
    assert (t.entry_i, t.exit_i) == (1, 3)
    assert t.dir == -1 and t.ret == pytest.approx(-(80 / 100 - 1) - 0.002)


def test_funding_paid_by_long_received_by_short():
    fund = [0, 0, 0.001, 0, 0.001, 0]
    p = _prep([100] * 6, fund=fund)
    long_ = bt.run(p, np.array([1, 1, 1, 1, 1, 1]), cost=0)
    short = bt.run(p, np.array([-1] * 6), cost=0)
    # 第0根收盘发信号，第1根开盘进场；持有经过第2、4根内的两次结算
    assert long_.trades.ret.iloc[0] == pytest.approx(-0.002)
    assert short.trades.ret.iloc[0] == pytest.approx(0.002)


def test_stop_loss_and_gap():
    o = [100, 100, 100, 90]
    l = [100, 100, 99, 85]
    p = _prep(o, l=l, c=[100, 100, 99.5, 88], atr=1.0)
    r = bt.run(p, np.array([1, 1, 1, 1]), cost=0, stop_atr=2.0)  # 进场 100，止损 98
    t = r.trades.iloc[0]
    assert t.reason == "stop" and t.exit_i == 3
    assert t.exit_px == 90  # 跳空低开在止损之下，按开盘价成交
    assert len(r.trades) == 1  # 止损后信号未变，不再重新进场


def test_take_profit_and_time_exit():
    p = _prep([100, 100, 101, 102, 103], h=[100, 100, 104, 103, 104], atr=1.0)
    r = bt.run(p, np.array([1, 1, 1, 1, 1]), cost=0, stop_atr=5, tp_atr=3)
    assert r.trades.iloc[0].reason == "take_profit" and r.trades.iloc[0].exit_px == 103
    r = bt.run(p, np.array([1, 1, 1, 1, 1]), cost=0, max_hold_h=2)
    assert r.trades.iloc[0].reason == "time" and r.trades.iloc[0].exit_i == 2


def test_numba_and_python_paths_agree(frame):
    p = bt.Prepared.from_frame(frame)
    sig = STRATEGIES["ema_cross"].signal(frame, {"fast": 24, "slow": 168})
    args = (p.o.tolist(), p.h.tolist(), p.l.tolist(), p.c.tolist(), p.atr.tolist(),
            sig.astype(np.int64).tolist(), p.fund.tolist(), 0.0007, 3.0, 6.0, 4.0, 48)
    py = bt._sim_core(*args)
    r = bt.run(p, sig, 0.0007, 3.0, 6.0, 4.0, 48)
    np.testing.assert_allclose(py[0], r.equity)
    np.testing.assert_allclose(py[8], r.trades.ret.to_numpy())


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategies_are_causal(frame, name):
    """截掉未来数据后，过去的信号必须完全一样（无未来函数）。"""
    s = STRATEGIES[name]
    params = s.param_sets()[0]
    full = s.signal(frame, params)
    cut = len(frame) - 300
    part = s.signal(frame.iloc[:cut], params)
    assert set(np.unique(full)) <= {-1, 0, 1}
    np.testing.assert_array_equal(full[:cut], part)


def test_funding_alignment(frame):
    # 资金费每 8 小时结算一次，并被分配到恰好一根 K 线上
    paid = frame["funding_paid"]
    assert (paid != 0).sum() == pytest.approx(len(frame) / 8, abs=2)
    # 已知费率只在结算所在 K 线收盘后才变化
    first = paid.ne(0).to_numpy().argmax()
    assert np.isnan(frame["funding_rate"].iloc[first - 1])
    assert frame["funding_rate"].iloc[first] == pytest.approx(paid.iloc[first])


def test_predictive_power_detects_signal(frame):
    ic = predictive_power(frame, horizons_h=[24])
    assert {"ic", "t", "q5_up_rate"} <= set(ic.columns)
    assert ic["ic"].abs().max() < 1


def test_walk_forward_runs(frame):
    cfg = BacktestConfig(folds=3)
    res = evaluate_symbol(frame, cfg, get_strategies("ema_cross,funding_fade"))
    assert set(res.oos["strategy"]) == {"ema_cross", "funding_fade", "AUTO", "buy_hold"}
    assert len(res.curves["ema_cross"]) == len(frame) - int(len(frame) * cfg.initial_train_frac)
    assert "ema_cross" in res.best
