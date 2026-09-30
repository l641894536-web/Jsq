"""指标库：74 个预注册信号的实现（定义见 docs/indicators_protocol.md 第 3 节）。

实现细节（在看结果之前确定）：
- 全部用复权价，t 日收盘计算；
- 滚动窗口 ≥20 日时允许窗口内有 ≤20% 的缺失（停牌），短窗口要求完整；
- 指数平均（EMA/Wilder）用 adjust=False 递推。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .panel import Panel


def _df(P: Panel, key: str, arr) -> pd.DataFrame:
    return P.get("df_" + key, lambda: pd.DataFrame(arr))


def _mp(w: int) -> int:
    return w if w < 20 else int(np.ceil(w * 0.8))


def roll(df: pd.DataFrame, w: int):
    return df.rolling(w, min_periods=_mp(w))


def ma(P: Panel, w: int) -> pd.DataFrame:
    return P.get(f"ma{w}", lambda: roll(_df(P, "C", P.C), w).mean())


def ema(df: pd.DataFrame, span: int | None = None, alpha: float | None = None) -> pd.DataFrame:
    if alpha is not None:
        return df.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()
    return df.ewm(span=span, adjust=False, ignore_na=True).mean()


def macd(P: Panel, f: int, s: int, m: int):
    def calc():
        C = _df(P, "C", P.C).ffill()
        dif = ema(C, span=f) - ema(C, span=s)
        dea = ema(dif, span=m)
        return dif, dea, 2 * (dif - dea)
    return P.get(f"macd_{f}_{s}_{m}", calc)


def rsi(P: Panel, n: int) -> pd.DataFrame:
    def calc():
        r = _df(P, "C", P.C).ffill().diff()
        up = ema(r.clip(lower=0), alpha=1 / n)
        dn = ema((-r).clip(lower=0), alpha=1 / n)
        return 100 * up / (up + dn).replace(0, np.nan)   # 等价于 100 − 100/(1+up/dn)，无下跌时 = 100
    return P.get(f"rsi{n}", calc)


def kdj(P: Panel):
    def calc():
        C = _df(P, "C", P.C)
        lo = roll(_df(P, "L", P.L), 9).min()
        hi = roll(_df(P, "H", P.H), 9).max()
        rsv = (C - lo) / (hi - lo).replace(0, np.nan) * 100
        k = ema(rsv, alpha=1 / 3)
        d = ema(k, alpha=1 / 3)
        return k, d, 3 * k - 2 * d
    return P.get("kdj", calc)


def ret_df(P: Panel) -> pd.DataFrame:
    return _df(P, "ret", P.ret)


def _limits(P: Panel):
    return P.limit_hits(P.get("tol", lambda: 0.005))


def _cci(P: Panel, n: int = 14) -> pd.DataFrame:
    tp = (_df(P, "H", P.H) + _df(P, "L", P.L) + _df(P, "C", P.C)) / 3
    m = roll(tp, n).mean()
    arr = tp.to_numpy(dtype=np.float64)
    out = np.full(arr.shape, np.nan)
    from numpy.lib.stride_tricks import sliding_window_view
    for j0 in range(0, arr.shape[1], 800):
        blk = arr[:, j0:j0 + 800]
        win = sliding_window_view(blk, n, axis=0)  # (T-n+1, cols, n)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(win, axis=2)
            mad = np.nanmean(np.abs(win - mean[:, :, None]), axis=2)
        out[n - 1:, j0:j0 + 800] = mad
    mad = pd.DataFrame(out)
    return (tp - m) / (0.015 * mad.replace(0, np.nan))


def _streak(P: Panel) -> np.ndarray:
    r = np.nan_to_num(P.ret, nan=0.0)
    out = np.zeros_like(r)
    cur = np.zeros(r.shape[1], dtype=np.float32)
    for t in range(r.shape[0]):
        s = np.sign(r[t])
        cur = np.where(s > 0, np.where(cur > 0, cur + 1, 1), np.where(s < 0, np.where(cur < 0, cur - 1, -1), 0))
        out[t] = cur
    out[~np.isfinite(P.C)] = np.nan
    return out


def _cross_up(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    return ((a > b) & (a.shift(1) <= b.shift(1))).astype(np.float32).where(a.notna() & b.notna())


def build_registry() -> dict:
    R: dict = {}

    def reg(name):
        def deco(fn):
            R[name] = fn
            return fn
        return deco

    for n in (5, 10, 20, 60, 120, 250):
        R[f"bias_{n}"] = lambda P, n=n: _df(P, "C", P.C) / ma(P, n) - 1
    R["ma_align"] = lambda P: ((ma(P, 5) > ma(P, 10)) & (ma(P, 10) > ma(P, 20)) & (ma(P, 20) > ma(P, 60))).astype(np.float32) \
        - ((ma(P, 5) < ma(P, 10)) & (ma(P, 10) < ma(P, 20)) & (ma(P, 20) < ma(P, 60))).astype(np.float32)
    for s, l in ((5, 20), (10, 60), (20, 120)):
        R[f"macross_{s}_{l}"] = lambda P, s=s, l=l: ma(P, s) / ma(P, l) - 1
    for n in (1, 5, 20, 60, 120, 250):
        R[f"ret_{n}"] = lambda P, n=n: _df(P, "C", P.C) / _df(P, "C", P.C).shift(n) - 1
    R["mom_12_1"] = lambda P: _df(P, "C", P.C).shift(20) / _df(P, "C", P.C).shift(250) - 1
    for (f, s, m), tag in (((12, 26, 9), "12_26"), ((6, 13, 5), "6_13")):
        R[f"macd_dif_{tag}"] = lambda P, f=f, s=s, m=m: macd(P, f, s, m)[0] / _df(P, "C", P.C)
        R[f"macd_dea_{tag}_{m}"] = lambda P, f=f, s=s, m=m: macd(P, f, s, m)[1] / _df(P, "C", P.C)
        R[f"macd_hist_{tag}_{m}"] = lambda P, f=f, s=s, m=m: macd(P, f, s, m)[2] / _df(P, "C", P.C)
    for n in (6, 14, 24):
        R[f"rsi_{n}"] = lambda P, n=n: rsi(P, n)
    R["kdj_k"] = lambda P: kdj(P)[0]
    R["kdj_d"] = lambda P: kdj(P)[1]
    R["kdj_j"] = lambda P: kdj(P)[2]
    R["wr_14"] = lambda P: (roll(_df(P, "H", P.H), 14).max() - _df(P, "C", P.C)) / \
        (roll(_df(P, "H", P.H), 14).max() - roll(_df(P, "L", P.L), 14).min()).replace(0, np.nan) * 100
    R["cci_14"] = lambda P: _cci(P, 14)

    def boll(P):
        m = ma(P, 20)
        sd = roll(_df(P, "C", P.C), 20).std()
        return m, sd
    R["boll_pos_20"] = lambda P: (_df(P, "C", P.C) - (boll(P)[0] - 2 * boll(P)[1])) / (4 * boll(P)[1]).replace(0, np.nan)
    R["boll_width_20"] = lambda P: 4 * boll(P)[1] / boll(P)[0]
    for n in (20, 60, 250):
        R[f"dist_high_{n}"] = lambda P, n=n: _df(P, "C", P.C) / roll(_df(P, "H", P.H), n).max() - 1
        R[f"dist_low_{n}"] = lambda P, n=n: _df(P, "C", P.C) / roll(_df(P, "L", P.L), n).min() - 1
    R["new_high_250"] = lambda P: (_df(P, "C", P.C) >= roll(_df(P, "C", P.C), 250).max().shift(1)).astype(np.float32) \
        .where(roll(_df(P, "C", P.C), 250).max().shift(1).notna())
    for n in (20, 60):
        R[f"vol_{n}"] = lambda P, n=n: roll(ret_df(P), n).std()

    def atr(P):
        pc = pd.DataFrame(P.prev_close)
        H, L = _df(P, "H", P.H), _df(P, "L", P.L)
        tr = np.fmax(np.fmax((H - L).to_numpy(), (H - pc).abs().to_numpy()), (L - pc).abs().to_numpy())
        return ema(pd.DataFrame(tr), alpha=1 / 14) / _df(P, "C", P.C)
    R["atr_14"] = atr
    R["amplitude_20"] = lambda P: roll((_df(P, "H", P.H) - _df(P, "L", P.L)) / pd.DataFrame(P.prev_close), 20).mean()
    R["max_ret_20"] = lambda P: roll(ret_df(P), 20).max()
    R["min_ret_20"] = lambda P: roll(ret_df(P), 20).min()
    R["skew_20"] = lambda P: roll(ret_df(P), 20).skew()
    A = lambda P: _df(P, "A", P.A)  # noqa: E731
    R["amt_ratio_5_20"] = lambda P: roll(A(P), 5).mean() / roll(A(P), 20).mean()
    R["amt_ratio_20_60"] = lambda P: roll(A(P), 20).mean() / roll(A(P), 60).mean()

    def pv_corr(P):
        dlv = np.log(_df(P, "V", P.V).where(_df(P, "V", P.V) > 0)).diff()
        return roll(ret_df(P), 20).corr(dlv)
    R["pv_corr_20"] = pv_corr

    def obv(P):
        V = _df(P, "V", P.V).fillna(0)
        o = (np.sign(ret_df(P).fillna(0)) * V).cumsum()
        return ((o - o.shift(20)) / roll(V, 20).sum().replace(0, np.nan)).where(_df(P, "C", P.C).notna())
    R["obv_chg_20"] = obv
    R["log_amount_20"] = lambda P: np.log(roll(A(P), 20).mean())
    R["amihud_20"] = lambda P: roll(ret_df(P).abs() / A(P) * 1e8, 20).mean()
    R["vol_chg_1"] = lambda P: np.log(_df(P, "V", P.V).where(_df(P, "V", P.V) > 0)).diff()
    R["abnormal_amt_1"] = lambda P: A(P) / roll(A(P), 20).mean().shift(1)
    R["streak"] = lambda P: pd.DataFrame(_streak(P))
    R["gap_1"] = lambda P: _df(P, "O", P.O) / pd.DataFrame(P.prev_close) - 1
    pc = lambda P: pd.DataFrame(P.prev_close)  # noqa: E731
    R["upper_shadow_5"] = lambda P: roll((_df(P, "H", P.H) - np.fmax(_df(P, "O", P.O), _df(P, "C", P.C))) / pc(P), 5).mean()
    R["lower_shadow_5"] = lambda P: roll((np.fmin(_df(P, "O", P.O), _df(P, "C", P.C)) - _df(P, "L", P.L)) / pc(P), 5).mean()
    R["limit_up_20"] = lambda P: pd.DataFrame(_limits(P)["up_close"].astype(np.float32)).rolling(20, min_periods=16).sum()
    R["limit_down_20"] = lambda P: pd.DataFrame(_limits(P)["down_close"].astype(np.float32)).rolling(20, min_periods=16).sum()
    R["close_pos_1"] = lambda P: (_df(P, "C", P.C) - _df(P, "L", P.L)) / (_df(P, "H", P.H) - _df(P, "L", P.L)).replace(0, np.nan)
    R["intraday_ret_1"] = lambda P: _df(P, "C", P.C) / _df(P, "O", P.O) - 1
    R["overnight_ret_5"] = lambda P: roll(np.log(_df(P, "O", P.O) / pc(P)), 5).sum()
    # 事件（1/0）
    R["ev_macd_golden"] = lambda P: _cross_up(macd(P, 12, 26, 9)[0], macd(P, 12, 26, 9)[1])
    R["ev_macd_dead"] = lambda P: _cross_up(macd(P, 12, 26, 9)[1], macd(P, 12, 26, 9)[0])

    def kdj_gold(P):
        k, d, _ = kdj(P)
        return (_cross_up(k, d) * (np.fmin(k.shift(1), d.shift(1)) < 20)).where(k.notna() & d.notna())
    R["ev_kdj_golden_low"] = kdj_gold
    R["ev_rsi6_oversold"] = lambda P: (rsi(P, 6) < 20).astype(np.float32).where(rsi(P, 6).notna())
    R["ev_rsi6_overbought"] = lambda P: (rsi(P, 6) > 80).astype(np.float32).where(rsi(P, 6).notna())
    R["ev_break_high_20"] = lambda P: (_df(P, "C", P.C) > roll(_df(P, "H", P.H), 20).max().shift(1)).astype(np.float32) \
        .where(roll(_df(P, "H", P.H), 20).max().shift(1).notna())
    R["ev_break_low_20"] = lambda P: (_df(P, "C", P.C) < roll(_df(P, "L", P.L), 20).min().shift(1)).astype(np.float32) \
        .where(roll(_df(P, "L", P.L), 20).min().shift(1).notna())
    R["ev_ma_golden_5_20"] = lambda P: _cross_up(ma(P, 5), ma(P, 20))
    R["ev_limit_up"] = lambda P: pd.DataFrame(_limits(P)["up_close"].astype(np.float32)).where(pd.DataFrame(np.isfinite(P.C)))
    R["ev_limit_down"] = lambda P: pd.DataFrame(_limits(P)["down_close"].astype(np.float32)).where(pd.DataFrame(np.isfinite(P.C)))
    return R


REGISTRY = build_registry()


def compute(name: str, P: Panel) -> np.ndarray:
    out = REGISTRY[name](P)
    arr = out.to_numpy(dtype=np.float32) if isinstance(out, pd.DataFrame) else np.asarray(out, dtype=np.float32)
    arr = arr.copy()
    arr[~np.isfinite(arr)] = np.nan
    arr[~np.isfinite(P.C)] = np.nan   # 当日停牌不出信号
    return arr


EVENT_SIGNALS = [k for k in REGISTRY if k.startswith("ev_")]
