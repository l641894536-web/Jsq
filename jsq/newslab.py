"""新闻事件研究：新闻报道量突增之后，价格是延续还是回吐？新闻情绪能不能判断方向？

为什么不做参数优化：新闻数据只有约 3 个月，事件数少，搜参数必然拟合噪音。
所以只检验事先定好的规则：
  事件     = 某主题的报道量超过过去 7 天均值 3 个标准差（取突增的第一个小时）
  延续性   = 事件前 2 根 K 线（覆盖新闻发生的那一小时）的涨跌方向 × 事件后 N 小时收益
  情绪方向 = (该小时情绪 - 过去 7 天平均情绪) 的符号 × 事件后 N 小时收益
  波动放大 = 事件后 N 小时的平均绝对涨跌 ÷ 普通时段的平均绝对涨跌
收益从“新闻可用后的下一根开盘”算起（新闻已额外延后 1 小时对齐），每笔扣一来一回成本。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .news import TOPIC_CN, TOPICS

HORIZONS = [1, 2, 4, 8, 12, 24]


def _z(x: pd.Series, n: int = 168) -> pd.Series:
    m = x.rolling(n, min_periods=n // 4).mean().shift(1)
    s = x.rolling(n, min_periods=n // 4).std().shift(1)
    return (x - m) / s.replace(0, np.nan)


def events(df: pd.DataFrame, topic: str, z: float = 3.0) -> pd.DataFrame:
    vc, tc = f"news_{topic}_vol", f"news_{topic}_tone"
    if vc not in df or df[vc].notna().sum() < 200:
        return pd.DataFrame()
    zv = _z(df[vc])
    tone_dev = df[tc] - df[tc].rolling(168, min_periods=42).mean().shift(1)
    spike = (zv > z) & ~(zv.shift(1) > z)
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    rows = []
    for i in np.flatnonzero(spike.to_numpy()):
        if i < 2 or i + 2 >= len(o):
            continue
        r = {"symbol": df.attrs.get("symbol"), "topic": topic, "time": df.index[i], "vol_z": zv.iloc[i],
             "pre": c[i] / o[i - 1] - 1, "tone_dev": tone_dev.iloc[i]}
        for h in HORIZONS:
            if i + 1 + h < len(o):
                r[f"fwd_{h}"] = o[i + 1 + h] / o[i + 1] - 1
        rows.append(r)
    return pd.DataFrame(rows)


def baseline_abs(df: pd.DataFrame) -> dict:
    o = df["open"]
    return {h: float((o.shift(-1 - h) / o.shift(-1) - 1).abs().mean()) for h in HORIZONS}


def summarize(ev: pd.DataFrame, base: dict[str, dict], cost: float) -> pd.DataFrame:
    """按 主题 × 标的组 汇总：延续性、情绪方向、波动放大倍数（均为基点）。"""
    from .cross import group_of
    if not len(ev):
        return pd.DataFrame()
    ev = ev.assign(group=ev["symbol"].map(group_of))
    rows = []
    for (topic, grp), g in ev.groupby(["topic", "group"]):
        for h in HORIZONS:
            col = f"fwd_{h}"
            x = g.dropna(subset=[col])
            if len(x) < 5:
                continue
            fwd = x[col].to_numpy()
            cont = np.sign(x["pre"].to_numpy()) * fwd - 2 * cost
            tone = x.dropna(subset=["tone_dev"])
            tsig = np.sign(tone["tone_dev"].to_numpy()) * tone[col].to_numpy() - 2 * cost

            def t(v):
                return v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if len(v) > 2 and v.std(ddof=1) > 0 else np.nan
            b = np.mean([base[s][h] for s in x["symbol"].unique() if s in base])
            rows.append({
                "topic": topic, "topic_cn": TOPIC_CN.get(topic, topic), "group": grp, "horizon_h": h,
                "events": len(x), "symbols": x["symbol"].nunique(),
                "follow_bps": cont.mean() * 1e4, "follow_t": t(cont), "follow_win": (cont > 0).mean(),
                "fade_bps": (-cont - 4 * cost).mean() * 1e4,
                "tone_bps": tsig.mean() * 1e4 if len(tsig) else np.nan, "tone_t": t(tsig) if len(tsig) else np.nan,
                "vol_ratio": np.abs(fwd).mean() / b if b > 0 else np.nan,
            })
    return pd.DataFrame(rows)


def run(frames: list[pd.DataFrame], cost: float, z: float = 3.0):
    evs, base = [], {}
    for f in frames:
        base[f.attrs["symbol"]] = baseline_abs(f)
        for topic in TOPICS:
            e = events(f, topic, z)
            if len(e):
                evs.append(e)
    ev = pd.concat(evs, ignore_index=True) if evs else pd.DataFrame()
    return ev, summarize(ev, base, cost)
