"""经过“整条路”检验的信号：当前状态、触发价、虚拟持仓（止损 / 止盈 / 到期）和最近的信号记录。

目前两条，都是按“先看方向”的滚动检验选出来、三段都选了同一组参数的：
  * 贵金属 72 小时通道突破（donchian n=72）：一路顺 50% 对随机 42%。突破后走不远，止损 2 份、止盈 3 份
  * 加密 布林带突破跟随（72 小时、2.5 倍标准差、只在低波动行情）：一路顺 56% 对随机 45%。突破后能走，
    止损 2 份、不设止盈、拿满 72 小时
1 份 = 2 倍 1 小时 ATR；到期按收盘平。
信号在 1 小时 K 线收盘时判断，下一根开盘进场；同一根 K 线同时碰到止损和止盈按止损算。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest as bt
from .regime import FILTERS, regimes
from .strategies import STRATEGIES

SIGNALS = [
    {"key": "metal_break", "name": "贵金属 72 小时通道突破", "strategy": "donchian", "params": {"n": 72},
     "filter": "all", "r_atr": 2.0, "stop_R": 2.0, "tp_R": 3.0, "max_h": 72,
     "symbols": ["XAUUSDT", "XAUTUSDT", "PAXGUSDT", "XAGUSDT", "XPTUSDT", "XPDUSDT"],
     "weak": {"XPDUSDT": "钯金上历史为负，仅供参考"}},
    {"key": "crypto_bb_break", "name": "加密 布林带突破跟随", "strategy": "bb_break", "params": {"window": 72, "k": 2.5},
     "filter": "lowvol", "r_atr": 2.0, "stop_R": 2.0, "tp_R": None, "max_h": 72,
     "symbols": ["BTCUSDT", "ETHUSDT"], "weak": {}},
]
NAMES = {"XAUUSDT": "黄金", "XAUTUSDT": "黄金(XAUT)", "PAXGUSDT": "黄金(PAXG)", "XAGUSDT": "白银",
         "XPTUSDT": "铂金", "XPDUSDT": "钯金", "BTCUSDT": "比特币", "ETHUSDT": "以太坊"}


def _events(df: pd.DataFrame, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    sig = STRATEGIES[cfg["strategy"]].signal(df, cfg["params"])
    prev = np.concatenate([[0], sig[:-1]])
    ev = np.flatnonzero((sig != 0) & (sig != prev))
    allowed = FILTERS.get(cfg["filter"])
    if allowed is not None:
        ev = ev[np.isin(regimes(df).to_numpy()[ev], allowed)]
    return sig, ev


def virtual_trades(df: pd.DataFrame, cfg: dict, cost: float = 0.0007) -> pd.DataFrame:
    """每个新信号一笔虚拟单：第 ev+1 根开盘进场，止损 / 止盈先碰到哪个按哪个出，满 max_h 小时按收盘平；
    数据结束时还没出场的标为“持仓中”，盈亏按最新收盘价算。R 为扣来回成本后的份数。"""
    p = bt.Prepared.from_frame(df)
    sig, ev = _events(df, cfg)
    H = max(1, int(round(cfg["max_h"] / p.bar_hours)))
    rows = []
    for e in ev:
        i0 = e + 1
        if i0 >= len(p.o):
            continue
        side, entry, R = int(sig[e]), p.o[i0], cfg["r_atr"] * p.atr[e]
        if not (np.isfinite(R) and R > 0):
            continue
        sl = entry - side * cfg["stop_R"] * R
        tp = entry + side * cfg["tp_R"] * R if cfg.get("tp_R") else np.nan       # 不设止盈：拿满 max_h
        status, px, xi = "持仓中", p.c[-1], len(p.c) - 1
        for i in range(i0, min(i0 + H, len(p.c))):
            if (p.l[i] <= sl) if side > 0 else (p.h[i] >= sl):
                status, px, xi = "止损", sl, i
                break
            if np.isfinite(tp) and ((p.h[i] >= tp) if side > 0 else (p.l[i] <= tp)):
                status, px, xi = "止盈", tp, i
                break
        else:
            if i0 + H <= len(p.c):
                status, px, xi = "到期", p.c[i0 + H - 1], i0 + H - 1
        rows.append({"entry_time": p.index[i0], "side": side, "entry": entry, "R": R, "stop": sl, "target": tp,
                     "expire": p.index[i0] + pd.Timedelta(hours=cfg["max_h"]), "status": status,
                     "exit_time": p.index[xi], "exit": px,
                     "ret_R": side * (px - entry) / R - 2 * cost * entry / R})
    return pd.DataFrame(rows)


def triggers(df: pd.DataFrame, cfg: dict) -> dict:
    """下一根 1 小时收盘的触发价。
    通道突破：高于 n 小时最高价 → 做多，低于 n 小时最低价 → 做空；持多时收盘低于 n/2 小时最低价状态结束（持空对称）。
    布林带突破：高于 均线 + k 倍标准差 → 做多，低于 均线 − k 倍标准差 → 做空，回到均线状态结束
    （均线和标准差按最近 window 小时算，新收盘会让它们略变，所以是近似价）。
    regime：当前行情状态；ok = 当前行情是否允许开新仓。"""
    bh = df.attrs.get("bar_hours", 1.0)
    allowed = FILTERS.get(cfg["filter"])
    reg = regimes(df).iloc[-1]
    out = {"regime": reg, "ok": allowed is None or reg in allowed}
    if cfg["strategy"] == "donchian":
        n = int(round(cfg["params"]["n"] / bh))
        out.update(up=float(df["high"].iloc[-n:].max()), down=float(df["low"].iloc[-n:].min()),
                   long_exit=float(df["low"].iloc[-n // 2:].min()), short_exit=float(df["high"].iloc[-n // 2:].max()))
    elif cfg["strategy"] == "bb_break":
        n, k = int(round(cfg["params"]["window"] / bh)), cfg["params"]["k"]
        c = df["close"].iloc[-n:]
        m, sd = float(c.mean()), float(c.std())
        out.update(up=m + k * sd, down=m - k * sd, long_exit=m, short_exit=m)
    return out


def summarize(tr: pd.DataFrame, since: pd.Timestamp | None = None) -> dict:
    t = tr[tr["status"] != "持仓中"]
    if since is not None:
        t = t[t["entry_time"] >= since]
    if not len(t):
        return {"n": 0}
    r = t["ret_R"]
    return {"n": len(t), "exp_R": r.mean(), "win": (r > 0).mean(),
            "tp": (t["status"] == "止盈").mean(), "sl": (t["status"] == "止损").mean()}
