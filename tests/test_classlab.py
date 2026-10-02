import numpy as np
import pandas as pd

from jsq.classlab import run_class, trade_stats
from jsq.data import load_frame
from jsq.regime import REGIMES, regimes
from jsq.synthetic import make_dataset


def _frames(tmp_path):
    syms = make_dataset(tmp_path, "1h", days=240)
    return [load_frame(s, "1h", tmp_path) for s in syms]


def test_regimes_valid_and_causal(tmp_path):
    f = _frames(tmp_path)[0]
    r = regimes(f)
    assert set(r.dropna().unique()) <= set(REGIMES)
    cut = len(f) - 400
    pd.testing.assert_series_equal(r.iloc[:cut], regimes(f.iloc[:cut]), check_names=False)


def test_trade_stats_expectancy_and_payoff():
    t = pd.DataFrame({"ret": [0.03, -0.01, -0.01, 0.03], "R": [3, -1, -1, 3], "hold_h": 5,
                      "symbol": ["A", "A", "B", "B"], "dir": [1, -1, 1, -1]})
    s = trade_stats(t)
    assert s["win_rate"] == 0.5 and s["payoff"] == 3.0
    assert np.isclose(s["exp_bps"], 100) and np.isclose(s["exp_R"], 1.0)
    assert s["sym_pos"] == 1.0


def test_run_class_end_to_end(tmp_path):
    res = run_class(_frames(tmp_path), "加密", cost=0.0007, strategies=["ema_cross", "shock"])
    assert {"ema_cross", "shock"} & set(res.oos["strategy"])
    assert {"exp_bps", "payoff", "t_R"} <= set(res.oos.columns)
    assert len(res.decay) and set(res.decay["horizon_h"]) <= {1, 2, 4, 8, 12, 24, 48, 72, 120, 168}
