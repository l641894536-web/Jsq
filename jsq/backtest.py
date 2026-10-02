"""逐 K 线回测引擎。

规则：
  * 第 i 根 K 线收盘产生信号，第 i+1 根开盘价成交（无未来函数）
  * 每次开仓/平仓扣 手续费+滑点
  * 持仓跨过资金费率结算时刻时按真实历史费率收/付资金费（多头付正费率，空头收）
  * 可选 ATR 止损、ATR 止盈、ATR 移动止损、最长持仓时间；同一根 K 线同时触发止损和止盈时按止损算（保守）
  * 被止损/止盈/超时平仓后，必须等信号变化才会再次同向开仓，防止反复进出
  * 1 倍杠杆、全仓复利，收益可以直接按杠杆倍数线性放大理解（不含爆仓）
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind

REASONS = ["signal", "stop", "take_profit", "trailing", "time", "end"]
REASON_CN = {"signal": "信号", "stop": "止损", "take_profit": "止盈", "trailing": "移动止损",
             "time": "超时", "end": "回测结束"}


def _sim_core(o, h, l, c, atr, sig, fund, cost, stop_atr, tp_atr, trail_atr, max_hold):
    n = len(c)
    nan = np.nan
    equity = np.empty(n)
    position = np.zeros(n, np.int8)
    t_ei = np.empty(n, np.int64)
    t_xi = np.empty(n, np.int64)
    t_dir = np.empty(n, np.int8)
    t_epx = np.empty(n)
    t_xpx = np.empty(n)
    t_fund = np.empty(n)
    t_ret = np.empty(n)
    t_rsn = np.empty(n, np.int8)
    k = 0
    eq = 1.0
    eq_entry = 1.0
    pos = 0
    epx = 0.0
    stop = nan
    tp = nan
    trail = nan
    best = 0.0
    held = 0
    facc = 0.0
    ei = 0
    block = 0
    for i in range(n):
        if i > 0:
            tgt = sig[i - 1]
            if block != 0 and tgt != block:
                block = 0
            if pos != 0 and tgt != pos:
                r = pos * (o[i] / epx - 1.0) - 2.0 * cost - facc
                if r < -1.0:
                    r = -1.0
                eq = eq_entry * (1.0 + r)
                t_ei[k] = ei
                t_xi[k] = i
                t_dir[k] = pos
                t_epx[k] = epx
                t_xpx[k] = o[i]
                t_fund[k] = facc
                t_ret[k] = r
                t_rsn[k] = 0
                k += 1
                pos = 0
            if pos == 0 and tgt != 0 and tgt != block:
                pos = tgt
                epx = o[i]
                ei = i
                eq_entry = eq
                facc = 0.0
                held = 0
                best = epx
                a = atr[i - 1]
                ok = a == a and a > 0
                stop = epx - pos * stop_atr * a if (ok and stop_atr > 0) else nan
                tp = epx + pos * tp_atr * a if (ok and tp_atr > 0) else nan
                trail = trail_atr * a if (ok and trail_atr > 0) else nan
        if pos != 0:
            rsn = -1
            xpx = 0.0
            s = stop
            s_rsn = 1
            if trail == trail:
                ts = best - pos * trail
                if s != s or (pos == 1 and ts > s) or (pos == -1 and ts < s):
                    s = ts
                    s_rsn = 3
            if pos == 1:
                if s == s and l[i] <= s:
                    xpx = min(o[i], s)
                    rsn = s_rsn
                elif tp == tp and h[i] >= tp:
                    xpx = max(o[i], tp)
                    rsn = 2
            else:
                if s == s and h[i] >= s:
                    xpx = max(o[i], s)
                    rsn = s_rsn
                elif tp == tp and l[i] <= tp:
                    xpx = min(o[i], tp)
                    rsn = 2
            if rsn < 0:
                facc += pos * fund[i]
                held += 1
                if pos == 1 and h[i] > best:
                    best = h[i]
                elif pos == -1 and l[i] < best:
                    best = l[i]
                if max_hold > 0 and held >= max_hold:
                    xpx = c[i]
                    rsn = 4
            if rsn >= 0:
                r = pos * (xpx / epx - 1.0) - 2.0 * cost - facc
                if r < -1.0:
                    r = -1.0
                eq = eq_entry * (1.0 + r)
                t_ei[k] = ei
                t_xi[k] = i
                t_dir[k] = pos
                t_epx[k] = epx
                t_xpx[k] = xpx
                t_fund[k] = facc
                t_ret[k] = r
                t_rsn[k] = rsn
                k += 1
                block = pos
                pos = 0
        if pos != 0:
            equity[i] = eq_entry * (1.0 + pos * (c[i] / epx - 1.0) - cost - facc)
        else:
            equity[i] = eq
        position[i] = pos
    if pos != 0:
        r = pos * (c[n - 1] / epx - 1.0) - 2.0 * cost - facc
        if r < -1.0:
            r = -1.0
        eq = eq_entry * (1.0 + r)
        t_ei[k] = ei
        t_xi[k] = n - 1
        t_dir[k] = pos
        t_epx[k] = epx
        t_xpx[k] = c[n - 1]
        t_fund[k] = facc
        t_ret[k] = r
        t_rsn[k] = 5
        k += 1
        equity[n - 1] = eq
    return equity, position, t_ei[:k], t_xi[:k], t_dir[:k], t_epx[:k], t_xpx[:k], t_fund[:k], t_ret[:k], t_rsn[:k]


try:  # 可选 numba 加速
    from numba import njit
    _sim_fast = njit(cache=True)(_sim_core)
    HAS_NUMBA = True
except Exception:  # pragma: no cover
    _sim_fast = None
    HAS_NUMBA = False


@dataclass
class Prepared:
    """一个标的回测所需的 numpy 数组，跑几百组参数时只准备一次。"""
    index: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    fund: np.ndarray
    bar_hours: float

    @classmethod
    def from_frame(cls, df: pd.DataFrame, atr_period: int = 14) -> "Prepared":
        f = lambda s: np.ascontiguousarray(s.to_numpy(dtype=float))
        return cls(df.index, f(df["open"]), f(df["high"]), f(df["low"]), f(df["close"]),
                   f(ind.atr(df, atr_period)), f(df["funding_paid"].fillna(0.0)),
                   float(df.attrs.get("bar_hours", 1.0)))


@dataclass
class Result:
    equity: np.ndarray       # 每根 K 线收盘时的净值（起始 1.0）
    position: np.ndarray     # 每根 K 线收盘时的仓位
    trades: pd.DataFrame     # 每笔交易


def run(p: Prepared, sig: np.ndarray, cost: float, stop_atr: float = 0.0, tp_atr: float = 0.0,
        trail_atr: float = 0.0, max_hold_h: float = 0.0) -> Result:
    max_hold = int(round(max_hold_h / p.bar_hours)) if max_hold_h else 0
    sig = np.ascontiguousarray(sig, dtype=np.int64)
    args_scalars = (float(cost), float(stop_atr or 0), float(tp_atr or 0), float(trail_atr or 0), int(max_hold))
    if HAS_NUMBA:
        out = _sim_fast(p.o, p.h, p.l, p.c, p.atr, sig, p.fund, *args_scalars)
    else:  # 纯 Python：列表下标比 numpy 标量下标快很多
        out = _sim_core(p.o.tolist(), p.h.tolist(), p.l.tolist(), p.c.tolist(), p.atr.tolist(),
                        sig.tolist(), p.fund.tolist(), *args_scalars)
    equity, position, ei, xi, d, epx, xpx, fund, ret, rsn = out
    trades = pd.DataFrame({
        "entry_i": ei, "exit_i": xi, "dir": d, "entry_px": epx, "exit_px": xpx,
        "funding": fund, "ret": ret, "reason": np.asarray(REASONS)[rsn.astype(int)] if len(rsn) else [],
    })
    if len(trades):
        trades["entry_time"] = p.index[trades["entry_i"].to_numpy()]
        # 出场发生在 exit_i 的开盘(信号)或盘中/收盘(止损等)，用开盘时间近似
        trades["exit_time"] = p.index[trades["exit_i"].to_numpy()]
        trades["hold_h"] = (trades["exit_i"] - trades["entry_i"] + (trades["reason"] != "signal")) * p.bar_hours
    else:
        trades["entry_time"] = pd.Series([], dtype="datetime64[ns, UTC]")
        trades["exit_time"] = pd.Series([], dtype="datetime64[ns, UTC]")
        trades["hold_h"] = pd.Series([], dtype=float)
    return Result(equity, position, trades)


TRADE_COLS = ["entry_i", "exit_i", "dir", "entry_px", "exit_px", "funding", "ret", "reason",
              "entry_time", "exit_time", "hold_h"]


def empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLS)


def bar_returns(equity: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[1.0], equity[:-1]])
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev > 0, equity / prev - 1.0, 0.0)
    return r


def metrics(bar_ret: np.ndarray, position: np.ndarray, trades: pd.DataFrame, bar_hours: float) -> dict:
    """绩效指标。bar_ret / position 为评估窗口内的逐 K 线数据，trades 为窗口内开仓的交易。"""
    n = len(trades)
    bpy = 365 * 24 / bar_hours
    m: dict = {"trades": n}
    if len(bar_ret):
        curve = np.cumprod(1 + bar_ret)
        peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
        m["total_return"] = float(curve[-1] - 1)
        m["max_drawdown"] = float((curve / peak - 1).min())
        sd = bar_ret.std()
        m["sharpe"] = float(bar_ret.mean() / sd * np.sqrt(bpy)) if sd > 0 else 0.0
        years = len(bar_ret) / bpy
        m["cagr"] = float(curve[-1] ** (1 / years) - 1) if years > 0 and curve[-1] > 0 else -1.0
        m["calmar"] = m["cagr"] / abs(m["max_drawdown"]) if m["max_drawdown"] < 0 else 0.0
        m["exposure"] = float(np.mean(position != 0))
    else:
        m.update(total_return=0.0, max_drawdown=0.0, sharpe=0.0, cagr=0.0, calmar=0.0, exposure=0.0)
    if n:
        r = trades["ret"].to_numpy()
        wins, losses = r[r > 0], r[r <= 0]
        m["win_rate"] = float(len(wins) / n)
        m["avg_trade"] = float(r.mean())
        m["avg_win"] = float(wins.mean()) if len(wins) else 0.0
        m["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
        m["profit_factor"] = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
        m["t_stat"] = float(r.mean() / r.std(ddof=1) * np.sqrt(n)) if n > 1 and r.std(ddof=1) > 0 else 0.0
        m["avg_hold_h"] = float(trades["hold_h"].mean())
        m["funding_pnl"] = float(-trades["funding"].sum())
        for side, d in (("long", 1), ("short", -1)):
            rs = r[trades["dir"].to_numpy() == d]
            m[f"{side}_trades"] = int(len(rs))
            m[f"{side}_win_rate"] = float((rs > 0).mean()) if len(rs) else np.nan
            m[f"{side}_avg"] = float(rs.mean()) if len(rs) else np.nan
    else:
        m.update(win_rate=np.nan, avg_trade=np.nan, avg_win=np.nan, avg_loss=np.nan, profit_factor=np.nan,
                 t_stat=0.0, avg_hold_h=np.nan, funding_pnl=0.0, long_trades=0, long_win_rate=np.nan,
                 long_avg=np.nan, short_trades=0, short_win_rate=np.nan, short_avg=np.nan)
    return m


def window_metrics(res: Result, lo: int, hi: int, bar_hours: float, br: np.ndarray | None = None) -> dict:
    """[lo, hi) 根 K 线区间的指标；交易按开仓所在区间归属。"""
    br = bar_returns(res.equity) if br is None else br
    t = res.trades
    if len(t):
        ei = t["entry_i"].to_numpy()
        t = t[(ei >= lo) & (ei < hi)]
    return metrics(br[lo:hi], res.position[lo:hi], t, bar_hours)
