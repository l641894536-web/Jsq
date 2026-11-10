"""黄金白银日内短线：不用1R/2R，用K线和日内高低点做（5分钟线，2021-11 → 2026-09，当天进当天出）。
一天 = 纽约17:00到次日17:00（金银的交易日）。昨高/昨低 = 上一个交易日的最高/最低；日内高/低 = 今天到目前为止的最高/最低。
S1 假跌破昨低收回做多（假突破昨高收回做空）：先跌破昨低，15分钟收盘重新站回昨低上方 → 做多；止损=跌破时的最低点下方；目标=当时的日内最高点；到不了就收盘平
S2 回踩日内低点不破做多（冲日内高点不过做空）：日内低点已经2小时没破，价格回到低点上方0.1%以内，15分钟收阳且收在前一根最高之上 → 做多；止损=日内低点下方；目标=日内最高点
S3 突破亚洲盘区间顺势：前8小时的最高/最低是区间，之后15分钟收盘突破区间高点 → 做多；止损=区间中点；出场=某根1小时线收盘跌破前一根1小时线的最低点，或收盘平
S4 突破昨高顺势做多（跌破昨低做空）：15分钟收盘站上昨高 → 做多；止损=前1小时最低点下方；出场同 S3
成本：来回 0.1%。结果按100U开5倍（500U）折成每次赚亏多少U。牛熊=自身200日线。
用法：python3 intraday_bt.py"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X

COST, BUF = 0.001, 0.0005


def walk(o, h, l, c, i0, side, entry, stop, target, hours_end, trail):
    """从5分钟线 i0+1 起走到当天结束。trail=True：每满1小时检查'这1小时收盘是否越过前1小时的最低(高)点'。返回(出场价, 原因)"""
    n = len(c)
    for j in range(i0 + 1, n):
        if side * (l[j] if side == 1 else h[j]) <= side * stop:
            return (min(o[j], stop) if side == 1 else max(o[j], stop)), "stop"
        if target is not None and side * ((h[j] if side == 1 else l[j]) - target) >= 0:
            return target, "target"
        if trail and (j + 1) % 12 == 0 and j >= 23:          # 一小时收完
            ph_lo, ph_hi = l[j - 23:j - 11].min(), h[j - 23:j - 11].max()
            if (side == 1 and c[j] < ph_lo) or (side == -1 and c[j] > ph_hi):
                return c[j], "trail"
    return c[n - 1], "eod"


def run(sym, grp, bull):
    d = load.dukascopy(sym, interval="5m", start="2021-06").sort_values("ts").reset_index(drop=True)
    ny = d.ts.dt.tz_convert("America/New_York")
    d["day"] = (ny + pd.Timedelta(hours=7)).dt.tz_localize(None).dt.normalize()
    out, prev = [], None
    for day, g in d.groupby("day"):
        if len(g) < 200:           # 半天/节假日跳过
            prev = None if len(g) < 100 else (g.high.max(), g.low.min()); continue
        o, h, l, c = (g[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        n = len(c); pdh, pdl = prev if prev else (np.nan, np.nan)
        prev = (h.max(), l.min())
        if day < pd.Timestamp("2021-11-01") or not np.isfinite(pdh): continue
        b = bull.reindex([day], method="ffill").iloc[0]
        if pd.isna(b): continue
        env = "bull" if b == 1 else "bear"
        rh, rl = np.maximum.accumulate(h), np.minimum.accumulate(l)          # 日内到目前的高低
        done = set()
        def rec(setup, side, i, entry, stop, target, trail):
            if (setup, side) in done or not (side * (entry - stop) > 0): return
            if target is not None and side * (target - entry) < 0.002 * entry: return
            done.add((setup, side))
            px, why = walk(o, h, l, c, i, side, entry, stop, target, n, trail)
            ret = side * (px / entry - 1) - COST
            out.append(dict(sym=sym, grp=grp, day=day, env=env, setup=setup, dir="long" if side == 1 else "short", ret=ret, gross=ret + COST,
                            risk=side * (entry - stop) / entry, why=why, hr=i // 12))
        ah, al = h[:96].max(), l[:96].min()
        for i in range(5, n - 6, 3):                     # 每根15分钟线收盘（i = 这根15分钟线的最后一根5分钟线）
            if (i + 1) % 3: continue
            bo, bc, bh, bl = o[i - 2], c[i], h[i - 2:i + 1].max(), l[i - 2:i + 1].min()
            pc, ph, pl_ = c[i - 3], h[i - 5:i - 2].max(), l[i - 5:i - 2].min()
            # S1 假突破收回
            if rl[i] <= pdl and bc > pdl and (bl <= pdl or pc <= pdl): rec("S1 假跌破昨低收回", 1, i, bc, rl[i] * (1 - BUF), rh[i], False)
            if rh[i] >= pdh and bc < pdh and (bh >= pdh or pc >= pdh): rec("S1 假跌破昨低收回", -1, i, bc, rh[i] * (1 + BUF), rl[i], False)
            # S2 回踩日内低点不破
            if i >= 48 and (rh[i] - rl[i]) / rl[i] >= 0.004:
                if rl[i] == rl[i - 24] and bl <= rl[i] * 1.001 and bc > bo and bc > ph: rec("S2 回踩日内低点不破", 1, i, bc, rl[i] * (1 - BUF), rh[i], False)
                if rh[i] == rh[i - 24] and bh >= rh[i] * 0.999 and bc < bo and bc < pl_: rec("S2 回踩日内低点不破", -1, i, bc, rh[i] * (1 + BUF), rl[i], False)
            # S3 亚洲盘区间突破
            if i >= 96:
                if bc > ah and pc <= ah: rec("S3 突破亚洲盘区间", 1, i, bc, (ah + al) / 2, None, True)
                if bc < al and pc >= al: rec("S3 突破亚洲盘区间", -1, i, bc, (ah + al) / 2, None, True)
            # S4 突破昨高/昨低顺势
            if i >= 12:
                if bc > pdh and pc <= pdh: rec("S4 突破昨高顺势", 1, i, bc, l[i - 11:i + 1].min() * (1 - BUF), None, True)
                if bc < pdl and pc >= pdl: rec("S4 突破昨高顺势", -1, i, bc, h[i - 11:i + 1].max() * (1 + BUF), None, True)
    return pd.DataFrame(out)


if __name__ == "__main__":
    us = load.us_daily(["GC=F", "SI=F"]); us["date"] = pd.to_datetime(us.date); px = us.pivot(index="date", columns="ticker", values="close")
    T = pd.concat([run("XAUUSD", "黄金", X.bull_daily(px["GC=F"])), run("XAGUSD", "白银", X.bull_daily(px["SI=F"]))], ignore_index=True)
    T["u"] = T.ret * 500; T["half"] = np.where(T.day < pd.Timestamp("2024-05-01"), "h1", "h2")
    T.to_csv("intraday_trades.csv.gz", index=False)
    pd.set_option("display.width", 250); rows = []
    for (grp, setup, env, d), x in T.groupby(["grp", "setup", "env", "dir"]):
        if len(x) < 30: continue
        rows.append(dict(品种=grp, 做法=setup, 环境="牛" if env == "bull" else "熊", 方向="多" if d == "long" else "空", 笔数=len(x), 每月=round(len(x) / 59, 1), 赚的比例=f"{(x.ret > 0).mean()*100:.0f}%",
                         每次U=round(x.u.mean(), 2), 不扣费U=round(x.gross.mean() * 500, 2), 前段U=round(x[x.half == "h1"].u.mean(), 2), 后段U=round(x[x.half == "h2"].u.mean(), 2),
                         平均止损距离=f"{x.risk.mean()*100:.2f}%", 到目标=f"{(x.why == 'target').mean()*100:.0f}%", 打止损=f"{(x.why == 'stop').mean()*100:.0f}%"))
    R = pd.DataFrame(rows); print(R.to_string(index=False)); R.to_csv("intraday_report.csv", index=False)
