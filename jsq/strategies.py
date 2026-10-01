"""策略库。

每个策略是一个函数 fn(df, **params) -> np.ndarray[int8]，取值 1(多) / -1(空) / 0(空仓)，
表示“在第 i 根 K 线收盘时，希望持有的仓位”。回测引擎在第 i+1 根 K 线开盘价执行，
因此策略只要用到 <= i 的数据就不存在未来函数（tests 里有专门的因果性测试）。

参数里的周期统一用“小时”，自动换算成当前 K 线周期的根数。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import indicators as ind

FUNDING_Z_FLOOR = 0.02    # 年化资金费率 z 分数的标准差下限（2%/年）
PREMIUM_Z_FLOOR = 5e-5    # 溢价率 z 分数的标准差下限


def bars(df: pd.DataFrame, hours: float) -> int:
    return max(1, int(round(hours / df.attrs.get("bar_hours", 1.0))))


def hold_state(long_entry, long_exit, short_entry, short_exit) -> np.ndarray:
    """进出场条件 -> 持仓状态（带记忆）。NaN 视为 False。"""
    le = np.nan_to_num(np.asarray(long_entry, dtype=float)).astype(bool).tolist()
    lx = np.nan_to_num(np.asarray(long_exit, dtype=float)).astype(bool).tolist()
    se = np.nan_to_num(np.asarray(short_entry, dtype=float)).astype(bool).tolist()
    sx = np.nan_to_num(np.asarray(short_exit, dtype=float)).astype(bool).tolist()
    out = [0] * len(le)
    s = 0
    for i in range(len(le)):
        if s == 1 and (lx[i] or se[i]):
            s = 0
        elif s == -1 and (sx[i] or le[i]):
            s = 0
        if s == 0:
            if le[i] and not se[i]:
                s = 1
            elif se[i] and not le[i]:
                s = -1
        out[i] = s
    return np.array(out, dtype=np.int8)


def sign_state(x: pd.Series) -> np.ndarray:
    v = np.sign(np.nan_to_num(np.asarray(x, dtype=float)))
    return v.astype(np.int8)


def _cmp(a, op, b):
    """带 NaN 安全的比较，NaN 一律 False。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float) if not np.isscalar(b) else b
    with np.errstate(invalid="ignore"):
        r = {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    return r & ~np.isnan(a)


# ----------------------------------------------------------------------------- 资金费率类

def funding_fade(df, days=30, th=2.0, ex=0.5):
    """资金费率反向：费率异常偏高(多头拥挤)做空，异常偏低做多，回归正常后离场。"""
    z = ind.zscore(df["funding_ann"], bars(df, days * 24), floor=FUNDING_Z_FLOOR)
    return hold_state(_cmp(z, "<", -th), _cmp(z, ">", -ex), _cmp(z, ">", th), _cmp(z, "<", ex))


def funding_follow(df, days=30, th=1.0, ex=0.0):
    """资金费率顺势：费率上升说明多头在加仓，跟随拥挤方向（与 funding_fade 互为对照）。"""
    z = ind.zscore(df["funding_ann"], bars(df, days * 24), floor=FUNDING_Z_FLOOR)
    return hold_state(_cmp(z, ">", th), _cmp(z, "<", ex), _cmp(z, "<", -th), _cmp(z, ">", -ex))


def funding_level(df, hi=0.5, lo=-0.05):
    """资金费率绝对水平反向：年化费率 > hi 做空，< lo 做多；回到基准(约 11%/年)附近离场。"""
    f = df["funding_ann"]
    base = 0.11
    return hold_state(_cmp(f, "<", lo), _cmp(f, ">", base), _cmp(f, ">", hi), _cmp(f, "<", (hi + base) / 2))


def premium_fade(df, days=7, th=2.5, ex=0.5):
    """溢价(基差)反向：合约相对现货指数溢价异常高做空、折价异常深做多。小时级更新，比资金费率灵敏。"""
    z = ind.zscore(df["prem_close"], bars(df, days * 24), floor=PREMIUM_Z_FLOOR)
    return hold_state(_cmp(z, "<", -th), _cmp(z, ">", -ex), _cmp(z, ">", th), _cmp(z, "<", ex))


# ----------------------------------------------------------------------------- 纯 K 线类

def ema_cross(df, fast=24, slow=168):
    """均线趋势：快线在慢线上方持多，下方持空。"""
    d = ind.ema(df["close"], bars(df, fast)) - ind.ema(df["close"], bars(df, slow))
    return sign_state(d)


def donchian(df, n=72):
    """唐奇安通道突破（海龟）：突破 n 小时高点做多，跌破 n/2 小时低点离场；空头对称。"""
    hi = ind.highest(df["high"], bars(df, n)).shift(1)
    lo = ind.lowest(df["low"], bars(df, n)).shift(1)
    hx = ind.highest(df["high"], bars(df, n / 2)).shift(1)
    lx = ind.lowest(df["low"], bars(df, n / 2)).shift(1)
    c = df["close"]
    return hold_state(_cmp(c, ">", hi), _cmp(c, "<", lx), _cmp(c, "<", lo), _cmp(c, ">", hx))


def tsmom(df, lookback=168):
    """时间序列动量：过去 lookback 小时涨了就做多，跌了就做空。"""
    n = bars(df, lookback)
    return sign_state(df["close"] / df["close"].shift(n) - 1)


def rsi_revert(df, period=14, lo=30):
    """RSI 超买超卖反转：RSI<lo 做多、>100-lo 做空，回到 50 离场。"""
    hi = 100 - lo
    r = ind.rsi(df["close"], bars(df, period))
    return hold_state(_cmp(r, "<", lo), _cmp(r, ">", 50), _cmp(r, ">", hi), _cmp(r, "<", 50))


def bb_revert(df, window=72, k=2.5):
    """布林带反转：价格偏离均线 k 个标准差反向开仓，回到均线离场。"""
    z = ind.zscore(df["close"], bars(df, window))
    return hold_state(_cmp(z, "<", -k), _cmp(z, ">", 0), _cmp(z, ">", k), _cmp(z, "<", 0))


def macd_trend(df, scale=1):
    """MACD 柱方向：柱>0 持多，<0 持空。scale 放大周期（1 = 12/26/9 根 K 线）。"""
    _, _, hist = ind.macd(df["close"], 12 * scale, 26 * scale, 9 * scale)
    return sign_state(hist)


def taker_flow(df, window=12, th=1.5):
    """主动买卖流：一段时间内主动买入占比异常高 -> 做多（资金在追），异常低 -> 做空。"""
    n = bars(df, window)
    ratio = df["taker_buy_base"].rolling(n).sum() / df["volume"].rolling(n).sum().replace(0, np.nan)
    z = ind.zscore(ratio, bars(df, 7 * 24))
    return hold_state(_cmp(z, ">", th), _cmp(z, "<", 0), _cmp(z, "<", -th), _cmp(z, ">", 0))


# ----------------------------------------------------------------------------- 资金费率 + K 线组合

def trend_funding(df, fast=24, slow=168, th=1.0):
    """趋势 + 拥挤过滤：顺均线趋势开仓，但资金费率 z>th 时不追多、z<-th 时不追空。"""
    d = ind.ema(df["close"], bars(df, fast)) - ind.ema(df["close"], bars(df, slow))
    z = ind.zscore(df["funding_ann"], bars(df, 30 * 24), floor=FUNDING_Z_FLOOR).fillna(0).values
    t = sign_state(d)
    out = np.where((t == 1) & (z < th), 1, np.where((t == -1) & (z > -th), -1, 0))
    return out.astype(np.int8)


def breakout_funding(df, n=72, th=0.5):
    """突破 + 资金费率确认：向上突破时资金费率不拥挤(z<th)才做多，说明是空头被挤而非散户追高。"""
    hi = ind.highest(df["high"], bars(df, n)).shift(1)
    lo = ind.lowest(df["low"], bars(df, n)).shift(1)
    hx = ind.highest(df["high"], bars(df, n / 2)).shift(1)
    lx = ind.lowest(df["low"], bars(df, n / 2)).shift(1)
    z = ind.zscore(df["funding_ann"], bars(df, 30 * 24), floor=FUNDING_Z_FLOOR)
    c = df["close"]
    le = _cmp(c, ">", hi) & _cmp(z, "<", th)
    se = _cmp(c, "<", lo) & _cmp(z, ">", -th)
    return hold_state(le, _cmp(c, "<", lx), se, _cmp(c, ">", hx))


# ----------------------------------------------------------------------------- 持仓量 / 多空比 / 盘口 / 跨标的

def _ok(df, col):
    return col in df and df[col].notna().mean() > 0.3


def oi_flow(df, hours=4, th=1.0):
    """持仓量确认的突破：价格 hours 小时涨幅 z>th 且持仓量同步增加（新资金进场）做多，反之做空；动量消失离场。"""
    n = bars(df, hours)
    r = df["close"].pct_change(n)
    rz = r / (df["close"].pct_change().rolling(bars(df, 7 * 24)).std() * np.sqrt(n))
    doi = np.log(df["oi"]).diff(n)
    return hold_state(_cmp(rz, ">", th) & _cmp(doi, ">", 0), _cmp(rz, "<", 0),
                      _cmp(rz, "<", -th) & _cmp(doi, ">", 0), _cmp(rz, ">", 0))


def squeeze_fade(df, hours=4, th=1.5):
    """平仓驱动的急涨急跌反向：价格大幅波动但持仓量下降（空头回补/多头止损），行情难以持续，反向做。"""
    n = bars(df, hours)
    r = df["close"].pct_change(n)
    rz = r / (df["close"].pct_change().rolling(bars(df, 7 * 24)).std() * np.sqrt(n))
    doi = np.log(df["oi"]).diff(n)
    return hold_state(_cmp(rz, "<", -th) & _cmp(doi, "<", 0), _cmp(rz, ">", 0),
                      _cmp(rz, ">", th) & _cmp(doi, "<", 0), _cmp(rz, "<", 0))


def crowd_fade(df, col="global_ls", th=1.5):
    """多空比反向：账户多空比（散户）异常偏多做空、异常偏空做多，回到均值离场。"""
    z = ind.zscore(np.log(df[col].where(df[col] > 0)), bars(df, 7 * 24))
    return hold_state(_cmp(z, "<", -th), _cmp(z, ">", 0), _cmp(z, ">", th), _cmp(z, "<", 0))


def smart_follow(df, th=1.5):
    """跟随大户：大户持仓多空比相对散户账户多空比异常偏多做多，反之做空。"""
    x = (np.log(df["top_pos_ls"].where(df["top_pos_ls"] > 0))
         - np.log(df["global_ls"].where(df["global_ls"] > 0)))
    z = ind.zscore(x, bars(df, 7 * 24))
    return hold_state(_cmp(z, ">", th), _cmp(z, "<", 0), _cmp(z, "<", -th), _cmp(z, ">", 0))


def book_imbalance(df, hours=4, th=1.0, side=1):
    """盘口失衡：±1% 内买盘明显厚于卖盘。side=1 跟随（买盘厚做多），side=-1 反向（厚盘是诱多/挂单墙）。"""
    x = df["imb1_mean"].rolling(bars(df, hours)).mean()
    z = ind.zscore(x, bars(df, 7 * 24)) * side
    return hold_state(_cmp(z, ">", th), _cmp(z, "<", 0), _cmp(z, "<", -th), _cmp(z, ">", 0))


def peer_lead(df, hours=4, th=1.5):
    """参照标的领先：参照（BTC/QQQ/黄金/WTI）先大涨而本标的还没跟上时做多，反之做空。"""
    n = bars(df, hours)
    vol = df["peer_close"].pct_change().rolling(bars(df, 7 * 24)).std() * np.sqrt(n)
    pz = df["peer_close"].pct_change(n) / vol
    own = df["close"].pct_change(n) / vol
    gap = pz - own
    return hold_state(_cmp(pz, ">", th) & _cmp(gap, ">", th / 2), _cmp(gap, "<", 0),
                      _cmp(pz, "<", -th) & _cmp(gap, "<", -th / 2), _cmp(gap, ">", 0))


def rel_revert(df, days=3, th=2.0):
    """相对强弱回归：相对参照标的涨得过多做空、跌得过多做多（单腿配对交易）。"""
    n = bars(df, days * 24)
    spread = np.log(df["close"]) - np.log(df["peer_close"])
    z = ind.zscore(spread - spread.shift(n), bars(df, 30 * 24))
    return hold_state(_cmp(z, "<", -th), _cmp(z, ">", 0), _cmp(z, ">", th), _cmp(z, "<", 0))


def offhours_fade(df, th=1.5):
    """休市期间的涨跌在开盘后回吐：美股休市时价格偏离上次收盘过多，反向开仓，回到收盘价附近离场。"""
    from .cross import offhours_return
    r = offhours_return(df)
    vol = df["close"].pct_change().rolling(bars(df, 7 * 24)).std() * np.sqrt(bars(df, 16))
    z = (r / vol).ffill(limit=bars(df, 6))  # 开盘后几小时内沿用休市时的偏离判断
    return hold_state(_cmp(z, "<", -th), _cmp(z, ">", -0.3), _cmp(z, ">", th), _cmp(z, "<", 0.3))


# ----------------------------------------------------------------------------- 注册表

@dataclass
class Strategy:
    name: str
    label: str
    fn: Callable
    grid: dict
    needs: tuple = ()
    group: str = "K线"
    constraint: Callable | None = field(default=None, repr=False)

    def param_sets(self) -> list[dict]:
        keys = list(self.grid)
        combos = [dict(zip(keys, v)) for v in itertools.product(*(self.grid[k] for k in keys))]
        return [c for c in combos if self.constraint is None or self.constraint(c)]

    def available(self, df: pd.DataFrame) -> bool:
        return all(c in df and df[c].notna().mean() > 0.3 for c in self.needs)

    def signal(self, df: pd.DataFrame, params: dict) -> np.ndarray:
        return np.asarray(self.fn(df, **params), dtype=np.int8)


STRATEGIES: dict[str, Strategy] = {s.name: s for s in [
    Strategy("funding_fade", "资金费率反向", funding_fade,
             {"days": [7, 30], "th": [1.5, 2.0, 2.5], "ex": [0.0, 1.0]}, ("funding_ann",), "资金费率"),
    Strategy("funding_follow", "资金费率顺势", funding_follow,
             {"days": [7, 30], "th": [1.0, 2.0], "ex": [0.0]}, ("funding_ann",), "资金费率"),
    Strategy("funding_level", "资金费率绝对值反向", funding_level,
             {"hi": [0.3, 0.5, 1.0], "lo": [-0.1, 0.0]}, ("funding_ann",), "资金费率"),
    Strategy("premium_fade", "溢价/基差反向", premium_fade,
             {"days": [2, 7], "th": [2.0, 3.0], "ex": [0.5]}, ("prem_close",), "资金费率"),
    Strategy("ema_cross", "均线趋势", ema_cross,
             {"fast": [12, 24, 48], "slow": [72, 168, 336]}, (), "K线",
             constraint=lambda p: p["slow"] >= 3 * p["fast"]),
    Strategy("donchian", "通道突破", donchian, {"n": [24, 72, 168]}),
    Strategy("tsmom", "时序动量", tsmom, {"lookback": [24, 72, 168, 336]}),
    Strategy("rsi_revert", "RSI 反转", rsi_revert,
             {"period": [14, 28], "lo": [20, 25, 30]}, (), "K线"),
    Strategy("bb_revert", "布林带反转", bb_revert, {"window": [24, 72, 168], "k": [2.0, 2.5, 3.0]}),
    Strategy("macd_trend", "MACD 趋势", macd_trend, {"scale": [1, 2, 4, 8]}),
    Strategy("taker_flow", "主动买卖流", taker_flow,
             {"window": [4, 12, 24], "th": [1.0, 1.5, 2.0]}, ("taker_buy_base",), "K线"),
    Strategy("trend_funding", "趋势+费率拥挤过滤", trend_funding,
             {"fast": [24, 48], "slow": [168, 336], "th": [1.0, 2.0]}, ("funding_ann",), "组合"),
    Strategy("breakout_funding", "突破+费率确认", breakout_funding,
             {"n": [24, 72, 168], "th": [0.0, 1.0]}, ("funding_ann",), "组合"),
    Strategy("oi_flow", "持仓量确认突破", oi_flow, {"hours": [4, 12, 24], "th": [1.0, 2.0]}, ("oi",), "持仓/多空"),
    Strategy("squeeze_fade", "平仓急变反向", squeeze_fade, {"hours": [4, 12], "th": [1.5, 2.5]}, ("oi",), "持仓/多空"),
    Strategy("crowd_fade", "账户多空比反向", crowd_fade,
             {"col": ["global_ls", "top_acct_ls"], "th": [1.5, 2.5]}, ("global_ls", "top_acct_ls"), "持仓/多空"),
    Strategy("smart_follow", "跟随大户持仓", smart_follow, {"th": [1.0, 1.5, 2.0]}, ("top_pos_ls", "global_ls"), "持仓/多空"),
    Strategy("book_imbalance", "盘口失衡", book_imbalance,
             {"hours": [1, 4, 12], "th": [1.0, 2.0], "side": [1, -1]}, ("imb1_mean",), "盘口"),
    Strategy("peer_lead", "参照标的领先", peer_lead, {"hours": [1, 4], "th": [1.5, 2.5]}, ("peer_close",), "跨标的"),
    Strategy("rel_revert", "相对强弱回归", rel_revert, {"days": [1, 3, 7], "th": [1.5, 2.5]}, ("peer_close",), "跨标的"),
    Strategy("offhours_fade", "休市涨跌回吐", offhours_fade, {"th": [1.0, 1.5, 2.5]}, (), "跨标的"),
]}

def get_strategies(names: str | None = None) -> list[Strategy]:
    if not names:
        return list(STRATEGIES.values())
    out = []
    for n in names.split(","):
        n = n.strip()
        if n not in STRATEGIES:
            raise KeyError(f"未知策略 {n}，可选: {', '.join(STRATEGIES)}")
        out.append(STRATEGIES[n])
    return out
