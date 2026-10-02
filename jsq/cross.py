"""跨标的与交易时段变量。

同组参照（peer）：每个标的配一个“带头大哥”，看它是否领先 / 两者价差是否回归
  加密 -> BTC（BTC 自己 -> ETH）   美股 -> QQQ（QQQ -> SPY）
  贵金属 -> XAU（XAU -> PAXG）      能源 -> CL（CL -> BZ）
美股交易时段按美东时间 9:30-16:00（自动处理夏令时）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import TRADFI_KEYWORDS

PEERS = {"加密": "BTCUSDT", "美股/ETF": "QQQUSDT", "贵金属": "XAUUSDT", "能源": "CLUSDT"}
SELF_PEER = {"BTCUSDT": "ETHUSDT", "QQQUSDT": "SPYUSDT", "XAUUSDT": "PAXGUSDT", "CLUSDT": "BZUSDT"}


def group_of(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    for cat, keys in TRADFI_KEYWORDS.items():
        if base in keys:
            return "能源" if cat == "能源" else cat
    return "加密"


def peer_of(symbol: str) -> str:
    return SELF_PEER.get(symbol) or PEERS[group_of(symbol)]


def attach_peer(df: pd.DataFrame, data_dir: Path, interval: str) -> pd.DataFrame:
    from .data import load_frame, paths  # 延迟导入避免循环
    sym = df.attrs.get("symbol", "")
    peer = peer_of(sym)
    df["peer_close"] = np.nan
    if peer != sym and paths(data_dir, peer, interval)["klines"].exists():
        p = load_frame(peer, interval, data_dir, enrich=False)
        df["peer_close"] = p["close"].reindex(df.index).values
    df.attrs["peer"] = peer
    return df


def us_session(index: pd.DatetimeIndex, bar_hours: float = 1.0) -> np.ndarray:
    """K 线收盘时刻是否处在美股常规交易时段内。"""
    t = (index + pd.Timedelta(hours=bar_hours)).tz_convert("America/New_York")
    mins = t.hour * 60 + t.minute
    return np.asarray((t.weekday < 5) & (mins > 9 * 60 + 30) & (mins <= 16 * 60))


def offhours_return(df: pd.DataFrame) -> pd.Series:
    """非交易时段（夜盘、周末）里，从上一次美股收盘到现在的涨跌；交易时段内为 NaN。"""
    sess = us_session(df.index, df.attrs.get("bar_hours", 1.0))
    close = df["close"]
    last_sess_close = close.where(pd.Series(sess, index=df.index)).ffill()
    r = close / last_sess_close - 1
    return r.where(~sess)
