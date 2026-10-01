"""检验本身的“误报率”（size）：在没有任何可预测性的随机游走上，5% 水平的检验不应频繁拒绝。

这正是“长周期重叠回归 + 持续性信号”最容易骗人的地方：单用 Newey-West 或单用循环平移检验，
在 h=60/120 时误报率可达 10%~15%；ic_test 取两者较大的 p 值，把误报率压回名义水平附近。
"""

import numpy as np
import pandas as pd

from ashare_lab.core import stats


def _rejection_rate(h: int, signal: str, sims: int = 60, n: int = 2500, seed: int = 5) -> float:
    rng = np.random.default_rng(seed)
    rej = 0
    for _ in range(sims):
        s = pd.Series(np.cumsum(0.01 * rng.standard_normal(n + 300)))
        x = (s - s.shift(h)) if signal == "mom" else (s - s.rolling(250).mean())
        y = s.shift(-h) - s
        r = stats.ic_test(x.iloc[300:], y.iloc[300:], h, n_perm=200, rng=rng)
        rej += r["p"] < 0.05
    return rej / sims


def test_ic_test_size_on_random_walk():
    for h, sig in ((60, "mom"), (120, "mom"), (60, "dev")):
        rate = _rejection_rate(h, sig)
        assert rate <= 0.12, f"h={h} {sig} 误报率 {rate:.2f}"
