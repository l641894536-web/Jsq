"""合约线回测：进场固定，只比较出场方式。

数据：Dukascopy AMD/MU/DELL 1h（美股正常交易时段，每天约7根），近3年；
      另用币安股票永续 AMDUSDT/MUUSDT/DELLUSDT 1h（24小时交易，上市以来约半年）做核对。
"24小时高低点" = 最近 L 根小时线的最高/最低（正股时段数据 L=7 ≈ 1个交易日；永续 L=24）。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import numpy as np
import pandas as pd

COST = 0.001        # 往返手续费+滑点，占名义金额
BUF = 0.001         # 止损放在24h低点再下方 0.1%
MIN_RISK = 0.004    # 止损距离 < 0.4% 的信号跳过（太近，R值失真）
MAX_RISK = 0.08


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def signals(df, L, entry):
    c = df["close"]
    e20, e50 = ema(c, 20), ema(c, 50)
    up = e20 > e50
    cross_up = up & ~up.shift(1, fill_value=False)
    cross_dn = ~up & up.shift(1, fill_value=False)
    hiL = df["high"].rolling(L).max()
    loL = df["low"].rolling(L).min()
    env_up = c > c.shift(L)            # 过去24小时没在跌
    env_dn = c < c.shift(L)
    if entry == "cross":               # 小时线趋势刚转多/转空
        long_sig = cross_up & env_up
        short_sig = cross_dn & env_dn
    elif entry == "breakout":          # 趋势中突破前24h高/低点
        long_sig = up & (c > hiL.shift(1)) & env_up
        short_sig = ~up & (c < loL.shift(1)) & env_dn
    return long_sig, short_sig, cross_up, cross_dn, hiL, loL


def simulate(df, L, variant, entry="cross", max_hold_days=10, bars_per_day=7, stop_L=None, stop_atr=0.0, max_risk=MAX_RISK):
    """返回每笔交易（R为单位）。variant:
    A 固定止损拿大波段；B 1R平一半+剩余保本并跟踪24h低点；C 1R后保本+跟踪24h低点；D 1.5R全部止盈。
    所有版本：小时线趋势反向（EMA20/50反穿）或持仓满10个交易日也离场。"""
    df = df.reset_index(drop=True)
    long_sig, short_sig, cross_up, cross_dn, hiL, loL = signals(df, L, entry)
    o, h, l, c = (df[k].to_numpy() for k in ["open", "high", "low", "close"])
    ts = df["ts"].to_numpy()
    LS, SS, CU, CD = (x.to_numpy() for x in (long_sig, short_sig, cross_up, cross_dn))
    HI, LO = hiL.to_numpy(), loL.to_numpy()
    HI3 = df["high"].rolling(3 * L).max().to_numpy()
    _pc = df["close"].shift(1).fillna(df["close"])
    _tr = np.maximum(df["high"] - df["low"], np.maximum((df["high"] - _pc).abs(), (df["low"] - _pc).abs()))
    ATR = _tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    SL_HI = df["high"].rolling(stop_L or L).max().to_numpy()
    SL_LO = df["low"].rolling(stop_L or L).min().to_numpy()
    LO3 = df["low"].rolling(3 * L).min().to_numpy()
    max_bars = max_hold_days * bars_per_day
    trades = []
    i, n = 60, len(df)
    while i < n - 1:
        side = 1 if LS[i] else (-1 if SS[i] else 0)
        if side == 0:
            i += 1
            continue
        entry_px = c[i]
        stop = (SL_LO[i] * (1 - BUF) - stop_atr * ATR[i]) if side == 1 else (SL_HI[i] * (1 + BUF) + stop_atr * ATR[i])
        R = (entry_px - stop) * side
        if not (MIN_RISK * entry_px <= R <= max_risk * entry_px):
            i += 1
            continue
        pos = 1.0               # 剩余仓位
        realized = 0.0          # 已实现（R）
        armed = False           # 是否已到 1R（保本/跟踪启动）
        mfe = 0.0
        j = i + 1
        exit_reason = None
        while j < n:
            # ---- 本根K线内：先检查止损（保守），再检查止盈
            adverse = l[j] if side == 1 else h[j]
            fav = h[j] if side == 1 else l[j]
            if (adverse - stop) * side <= 0:
                px = stop if (o[j] - stop) * side > 0 else o[j]      # 跳空则按开盘价
                realized += pos * (px - entry_px) * side / R
                pos = 0
                exit_reason = "stop"
                break
            mfe = max(mfe, (fav - entry_px) * side / R)
            if variant in ("D", "G"):           # D 1.5R / G 2R 全部止盈（固定目标）
                tgt = entry_px + side * (1.5 if variant == "D" else 2.0) * R
                if (fav - tgt) * side >= 0:
                    px = tgt if (tgt - o[j]) * side > 0 else o[j]
                    realized += pos * (px - entry_px) * side / R
                    pos = 0
                    exit_reason = "target"
                    break
            if variant in ("B", "I", "H", "J") and pos == 1.0:   # B/I：1R 先平一半；H/J：2R 先平一半
                tgt = entry_px + side * (2.0 if variant in ("H", "J") else 1.0) * R
                if (fav - tgt) * side >= 0:
                    px = tgt if (tgt - o[j]) * side > 0 else o[j]
                    realized += 0.5 * (px - entry_px) * side / R
                    pos = 0.5
            if variant in ("B", "C", "E", "F", "G", "H", "I", "J") and mfe >= 1.0:
                armed = True
            # ---- 收盘后更新止损 / 检查离场
            if armed:
                if variant in ("E", "G"):   # 只保本，不跟踪
                    trail = entry_px
                elif variant in ("F", "I", "J"):  # 用3天高低点跟踪（大周期）
                    trail = LO3[j] * (1 - BUF) if side == 1 else HI3[j] * (1 + BUF)
                else:
                    trail = LO[j] * (1 - BUF) if side == 1 else HI[j] * (1 + BUF)
                new = max(entry_px, trail) if side == 1 else min(entry_px, trail)
                stop = max(stop, new) if side == 1 else min(stop, new)
            trend_flip = CD[j] if side == 1 else CU[j]
            if trend_flip or (j - i) >= max_bars or j == n - 1:
                realized += pos * (c[j] - entry_px) * side / R
                pos = 0
                exit_reason = "flip" if trend_flip else "time"
                break
            j += 1
        cost_R = COST * entry_px / R
        trades.append(dict(ts=ts[i], exit_ts=ts[j], side=side, entry=entry_px, R_pct=R / entry_px,
                           r=realized - cost_R, r_gross=realized, mfe=mfe, reason=exit_reason, bars=j - i))
        i = j + 1
    return pd.DataFrame(trades)


def summarize(t):
    if len(t) == 0:
        return {}
    eq = t.sort_values("ts")["r"].cumsum()
    dd = (eq - eq.cummax()).min()
    wins = t.r[t.r > 0].sum(); losses = -t.r[t.r < 0].sum()
    return {
        "笔数": len(t),
        "胜率": f"{(t.r > 0).mean():.0%}",
        "平均每笔R": round(t.r.mean(), 3),
        "总R": round(t.r.sum(), 1),
        "盈亏比PF": round(wins / losses, 2) if losses > 0 else np.inf,
        "最大回撤R": round(dd, 1),
        "去掉最大5笔后总R": round(t.r.sum() - t.r.nlargest(5).sum(), 1),
        "到过1R的单最后亏钱": f"{((t.mfe >= 1) & (t.r_gross < 0)).sum() / max((t.mfe >= 1).sum(), 1):.0%}",
    }


def regime_series():
    q = load.us_daily("QQQ", start="2019-01-01").set_index("date")["adj_close"]
    bull = (q > q.rolling(200).mean()).shift(1)        # 用前一天的状态，避免偷看
    return bull


VARIANTS = {"A": "A 现状：固定止损拿大波段", "B": "B 1R平一半+剩余保本跟踪",
            "C": "C 1R后保本+跟踪24h低点", "D": "D 1.5R全部止盈（纯短线）",
            "E": "E 1R后只挪保本不跟踪", "F": "F 1R后保本+跟踪3天低点"}


def run(source, entry="cross"):
    if source == "dk":
        raw = load.dukascopy(["AMDUSUSD", "MUUSUSD", "DELLUSUSD"], start="2023-08")
        raw["sym"] = raw.symbol.str.replace("USUSD", "")
        L, bpd, start = 7, 7, "2023-11-01"
    else:
        raw = load.binance("1h", ["AMDUSDT", "MUUSDT", "DELLUSDT"])
        raw["sym"] = raw.symbol.str.replace("USDT", "")
        L, bpd, start = 24, 24, None
    out = {}
    for v in VARIANTS:
        allt = []
        for s, g in raw.groupby("sym"):
            g = g.sort_values("ts").reset_index(drop=True)
            t = simulate(g, L, v, entry=entry, bars_per_day=bpd)
            t["sym"] = s
            if start:
                t = t[t.ts >= pd.Timestamp(start, tz="UTC")]
            allt.append(t)
        out[v] = pd.concat(allt, ignore_index=True)
    return out


if __name__ == "__main__":
    bull = regime_series()
    for source in ["dk", "bn"]:
        for entry in ["cross", "breakout"]:
            res = run(source, entry)
            print(f"\n===== 数据: {'正股小时线 近3年' if source=='dk' else '币安永续 上市以来'} | 进场: {entry}")
            rows = {VARIANTS[v]: summarize(t) for v, t in res.items()}
            print(pd.DataFrame(rows).T.to_string())
            if source == "dk":
                for v, t in res.items():
                    d = pd.to_datetime(t.ts).dt.tz_convert(None).dt.normalize()
                    t = t.assign(bull=bull.reindex(d).to_numpy())
                    for name, sub in [("牛(QQQ在200日线上)", t[t.bull == True]), ("熊(QQQ在200日线下)", t[t.bull == False])]:
                        s = summarize(sub)
                        print(f"   {v} {name}: 笔数{s.get('笔数')} 胜率{s.get('胜率')} 平均R{s.get('平均每笔R')} 总R{s.get('总R')} 回撤{s.get('最大回撤R')}")
            pd.concat([t.assign(variant=v) for v, t in res.items()]).to_csv(f"trades_{source}_{entry}.csv", index=False)
