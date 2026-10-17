"""港股收盘 → 次日开盘：合约在休市期间怎么走，开盘后是回落还是继续。

每一行 = 一个“收盘 → 下一交易日开盘”区间（周末、假期自动跨过去）：
  收盘快照   d 日 16:10 收市竞价后的正股（指数价格）与合约价
  白天涨跌   day_chg = d 日收盘 / 前一交易日收盘 - 1（看盘软件上“今天涨跌”）
  收盘后     合约在 18:00、21:30（美股开盘，夏令时）、次日 04:00（美股收盘）、开盘前 08:59 / 09:20 / 09:29 相对收盘的涨跌
  次日开盘   正股开盘跳空 gap = 09:30 那一分钟结束时的指数 / 收盘指数 - 1（含开盘第一分钟，近似）
  开盘后     合约 09:29→09:31（开盘那一下）、09:31→11:59、09:31→16:10
  夜盘参照   阿里巴巴美股合约（BABAUSDT）同一时段的涨跌，代表中概股夜里的整体情绪
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import hk

CHECKS = [("18:00", 0), ("21:30", 0), ("04:00", 1), ("08:59", None), ("09:20", None), ("09:29", None)]
COST_RT = 0.002   # 一来一回成本（手续费 2×0.05% + 滑点），休市时段价差较宽，按偏保守估计


def _lookup(df: pd.DataFrame, col: str) -> dict:
    h = df.index.tz_convert("Asia/Hong_Kong")
    return dict(zip(h.strftime("%Y-%m-%d %H:%M"), df[col].to_numpy()))


def overnight_table(df: pd.DataFrame, ref: pd.DataFrame | None = None) -> pd.DataFrame:
    sym = df.attrs.get("symbol", "")
    days = list(hk.panel(df)["close"].index)          # 港股交易日（指数在 09:31 后有成交）
    perp, idx = _lookup(df, "close"), _lookup(df, "index")
    refp = _lookup(ref, "close") if ref is not None else {}

    def at(book, day, hm):
        return book.get(f"{day} {hm}", np.nan)

    rows = []
    for k in range(1, len(days) - 1):
        prev, d, n = days[k - 1], days[k], days[k + 1]
        cal_next = (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        p_close, i_close = at(perp, d, "16:10"), at(idx, d, "16:10")
        i_prev = at(idx, prev, "16:10")
        if not (np.isfinite(p_close) and np.isfinite(i_close) and np.isfinite(i_prev)):
            continue
        r = {"symbol": sym, "day": d, "next_day": n, "weekend": (pd.Timestamp(n) - pd.Timestamp(d)).days > 1,
             "day_chg": i_close / i_prev - 1, "intraday": i_close / at(idx, d, "09:30") - 1,
             "basis_close": p_close / i_close - 1}
        for hm, off in CHECKS:
            day = d if off == 0 else (cal_next if off == 1 else n)
            r[f"pm_{hm}"] = at(perp, day, hm) / p_close - 1
        r["gap"] = at(idx, n, "09:30") / i_close - 1
        p0929, p0931 = at(perp, n, "09:29"), at(perp, n, "09:31")
        r["open_jump"] = p0931 / p0929 - 1                       # 合约在开盘那两分钟的变化
        r["after_1159"] = at(perp, n, "11:59") / p0931 - 1
        r["after_1610"] = at(perp, n, "16:10") / p0931 - 1
        r["total_1159"] = at(perp, n, "11:59") / p0929 - 1       # 从开盘前一刻到中午
        if refp:
            r["ref_overnight"] = at(refp, n, "09:29") / at(refp, d, "16:10") - 1
        rows.append(r)
    t = pd.DataFrame(rows)
    if len(t):
        t["overnight"] = t["pm_09:29"]
    return t


# ----------------------------------------------------------------------------- 统计

def _stat(x: pd.Series) -> dict:
    x = x.replace([np.inf, -np.inf], np.nan).dropna()
    n = len(x)
    if n < 5:
        return {"n": n}
    sd = x.std(ddof=1)
    return {"n": n, "mean_bps": x.mean() * 1e4, "median_bps": x.median() * 1e4, "up": (x > 0).mean(),
            "t": x.mean() / sd * np.sqrt(n) if sd > 0 else 0.0}


DAY_BUCKETS = [(-np.inf, -0.03, "大跌 ≤-3%"), (-0.03, -0.01, "下跌 -3%~-1%"), (-0.01, 0.01, "平 ±1%"),
               (0.01, 0.03, "上涨 1%~3%"), (0.03, np.inf, "大涨 ≥3%")]


def after_close(t: pd.DataFrame) -> pd.DataFrame:
    """按“白天涨跌”分组：收盘后合约在各时点相对收盘的平均涨跌与上涨概率。"""
    rows = []
    for lo, hi, lab in DAY_BUCKETS:
        g = t[(t["day_chg"] > lo) & (t["day_chg"] <= hi)]
        row = {"bucket": lab, "n": len(g), "day_chg_bps": g["day_chg"].mean() * 1e4 if len(g) else np.nan}
        for hm, _ in CHECKS:
            s = _stat(g[f"pm_{hm}"])
            row[f"{hm}_bps"], row[f"{hm}_up"], row[f"{hm}_t"] = s.get("mean_bps"), s.get("up"), s.get("t")
        rows.append(row)
    return pd.DataFrame(rows)


def slope(x: pd.Series, y: pd.Series) -> dict:
    m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    x, y = x[m].to_numpy(), y[m].to_numpy()
    if len(x) < 10:
        return {"n": len(x)}
    b, a = np.polyfit(x, y, 1)
    resid = y - (a + b * x)
    se = np.sqrt(resid.var(ddof=2) / ((x - x.mean()) ** 2).sum())
    return {"n": len(x), "slope": b, "t": b / se if se > 0 else 0.0, "corr": float(np.corrcoef(x, y)[0, 1])}


CASES = [("跌后反弹", -1, 1), ("跌后续跌", -1, -1), ("涨后补涨", 1, 1), ("涨后回落", 1, -1)]


def four_cases(t: pd.DataFrame, day_th: float = 0.01, night_th: float = 0.005) -> pd.DataFrame:
    """白天涨/跌 × 夜里合约涨/跌：次日开盘那一下与开盘后，是顺着夜里方向继续，还是回落。
    cont_* 为按夜里方向计算的收益（正 = 继续，负 = 回落）。"""
    rows = []
    for lab, ds, ns in CASES:
        m = (np.sign(t["day_chg"]) == ds) & (t["day_chg"].abs() > day_th) & \
            (np.sign(t["overnight"]) == ns) & (t["overnight"].abs() > night_th)
        g = t[m]
        s = np.sign(g["overnight"])
        row = {"case": lab, "n": len(g), "day_chg_bps": g["day_chg"].mean() * 1e4 if len(g) else np.nan,
               "overnight_bps": g["overnight"].mean() * 1e4 if len(g) else np.nan,
               "gap_bps": g["gap"].mean() * 1e4 if len(g) else np.nan}
        for key, col in (("open", "open_jump"), ("am", "after_1159"), ("total", "total_1159")):
            st = _stat(s * g[col])
            row[f"cont_{key}_bps"], row[f"cont_{key}_up"], row[f"cont_{key}_t"] = st.get("mean_bps"), st.get("up"), st.get("t")
        # 正股开盘跳空超过合约夜里已走的比例（= 开盘后合约还要继续追）
        row["gap_beyond"] = float((s * (g["gap"] - g["overnight"]) > 0).mean()) if len(g) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def decompose(t: pd.DataFrame) -> dict:
    """合约夜里的涨跌 = β × 中概夜盘（阿里美股合约）+ 自身部分；两部分开盘后各自是继续还是回吐。"""
    g = t.dropna(subset=["overnight", "ref_overnight", "total_1159"])
    if len(g) < 20:
        return {}
    beta = slope(g["ref_overnight"], g["overnight"])
    b = beta.get("slope", 0.0)
    market = b * g["ref_overnight"]
    own = g["overnight"] - market
    return {"beta": beta, "own_vs_after": slope(own, g["total_1159"]), "market_vs_after": slope(market, g["total_1159"]),
            "own_share": float((own ** 2).mean() / (g["overnight"] ** 2).mean()), "n": len(g)}


# ----------------------------------------------------------------------------- 交易规则

def rule_trades(t: pd.DataFrame, cost: float = COST_RT) -> pd.DataFrame:
    """几条事先定好的规则，按“收盘后”和“开盘前后”两个时段。ret 为扣成本后的收益。"""
    out = []

    def add(name, desc, side, ret, mask):
        g = t[mask & side.ne(0) & ret.notna()]
        if not len(g):
            return
        r = side[g.index] * ret[g.index] - cost
        for i, v in r.items():
            out.append({"rule": name, "desc": desc, "symbol": t.at[i, "symbol"], "day": t.at[i, "day"], "ret": v})

    dc, on = t["day_chg"], t["overnight"]
    big = dc.abs() > 0.03
    rev, mom = -np.sign(dc), np.sign(dc)
    for hm in ("21:30", "04:00", "09:29"):
        add(f"evening_rev_{hm}", f"白天涨跌超过 3%，16:10 反向做合约，{hm} 平仓", rev, t[f"pm_{hm}"], big)
        add(f"evening_mom_{hm}", f"白天涨跌超过 3%，16:10 顺势做合约，{hm} 平仓", mom, t[f"pm_{hm}"], big)
    bign = on.abs() > 0.02
    fade, follow = -np.sign(on), np.sign(on)
    add("preopen_fade_1159", "夜里合约涨跌超过 2%，09:29 反向，11:59 平仓", fade, t["total_1159"], bign)
    add("preopen_follow_1159", "夜里合约涨跌超过 2%，09:29 顺势，11:59 平仓", follow, t["total_1159"], bign)
    add("preopen_fade_0931", "夜里合约涨跌超过 2%，09:29 反向，09:31 平仓", fade, t["open_jump"], bign)
    add("preopen_follow_0931", "夜里合约涨跌超过 2%，09:29 顺势，09:31 平仓", follow, t["open_jump"], bign)
    return pd.DataFrame(out)


def rule_summary(tr: pd.DataFrame, split: str) -> pd.DataFrame:
    rows = []
    for (name, desc), g in tr.groupby(["rule", "desc"], sort=False):
        a, b, f = (_stat(x["ret"]) for x in (g[g["day"] < split], g[g["day"] >= split], g))
        rows.append({"rule": name, "desc": desc, "n": f["n"], "exp_bps": f.get("mean_bps"), "win": f.get("up"),
                     "t": f.get("t"), "first_bps": a.get("mean_bps"), "second_bps": b.get("mean_bps"),
                     "sym_pos": float((g.groupby("symbol")["ret"].mean() > 0).mean())})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- 实盘规则（报告与实时工具共用）

PATH_POINTS = [("收盘 16:10", None), ("18:00", "pm_18:00"), ("21:30 美股开盘", "pm_21:30"), ("次日 04:00 美股收盘", "pm_04:00"),
               ("08:59", "pm_08:59"), ("09:20 撮合", "pm_09:20"), ("09:29", "pm_09:29"), ("09:31 开盘后", "c_0931"),
               ("11:59", "c_1159")]


def add_cumulative(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["c_0931"] = (1 + t["pm_09:29"]) * (1 + t["open_jump"]) - 1
    t["c_1159"] = (1 + t["c_0931"]) * (1 + t["after_1159"]) - 1
    t["s0859_0931"] = (1 + t["c_0931"]) / (1 + t["pm_08:59"]) - 1      # 08:59 进、09:31 出
    t["s0859_1159"] = (1 + t["c_1159"]) / (1 + t["pm_08:59"]) - 1
    return t


def paths(t: pd.DataFrame, th: float = 0.01) -> list[dict]:
    """按 08:59 时合约相对收盘的涨跌分组，平均价格路径（相对收盘，基点）。"""
    t = add_cumulative(t)
    groups = {"up": t["pm_08:59"] > th, "down": t["pm_08:59"] < -th}
    out = []
    for lab, col in PATH_POINTS:
        row = {"t": lab}
        for g, m in groups.items():
            row[g] = 0.0 if col is None else float(t.loc[m, col].mean() * 1e4)
        out.append(row)
    return out


def preopen_rules(t: pd.DataFrame, basis_0931: pd.Series | None, split: str, cost: float = COST_RT) -> pd.DataFrame:
    """核心规则：夜里合约涨多了，08:59 做空；对照组与阈值、平仓时间的稳健性。"""
    t = add_cumulative(t)
    n859 = t["pm_08:59"]
    rows = []

    def add(name, side, ret, mask):
        m = (mask & ret.notna()).fillna(False).astype(bool)
        idx = m[m].index
        sd_ = side.loc[idx] if isinstance(side, pd.Series) else side
        r = (sd_ * ret.loc[idx] - cost).dropna()
        if len(r) < 8:
            return
        days, syms = t.loc[r.index, "day"], t.loc[r.index, "symbol"]
        a, b = r[days < split], r[days >= split]
        sd = r.std(ddof=1)
        rows.append({"rule": name, "n": len(r), "exp_bps": r.mean() * 1e4, "win": (r > 0).mean(),
                     "t": r.mean() / sd * np.sqrt(len(r)) if sd > 0 else 0, "first_bps": a.mean() * 1e4,
                     "second_bps": b.mean() * 1e4, "sym_pos": float((r.groupby(syms).mean() > 0).mean())})

    for th in (0.005, 0.01, 0.02):
        add(f"夜里涨 >{th:.1%}：08:59 做空，09:31 平", -1, t["s0859_0931"], n859 > th)
    add("夜里涨 1%~2%：08:59 做空，09:31 平", -1, t["s0859_0931"], (n859 > 0.01) & (n859 <= 0.02))
    if basis_0931 is not None:
        seq = pd.Series(np.where(basis_0931.reindex(t.index) > 0.003, t["s0859_1159"], t["s0859_0931"]), index=t.index)
        add("夜里涨 >1%：08:59 做空；09:31 合约仍比正股贵 >0.3% 就拿到 11:59", -1, seq, n859 > 0.01)
    add("对照：夜里跌 >1%：08:59 做多，09:31 平", 1, t["s0859_0931"], n859 < -0.01)
    # 开盘前顺着夜里方向追单（实盘最常见的做法）
    add("对照：夜里涨 >1%：08:59 追多，09:31 平", 1, t["s0859_0931"], n859 > 0.01)
    add("对照：夜里跌 >1%：08:59 追空，09:31 平", -1, t["s0859_0931"], n859 < -0.01)
    sb = np.sign(t["ref_overnight"]).where(t["ref_overnight"].abs() > 0.005, 0) if "ref_overnight" in t else None
    if sb is not None:
        add("阿里美股合约夜里涨/跌 >0.5%：09:31 同向开仓，11:59 平", sb, t["after_1159"], sb.ne(0))
    big = t["day_chg"].abs() > 0.03
    add("对照：白天涨跌 >3%，16:10 反向做，18:00 平", -np.sign(t["day_chg"]), t["pm_18:00"], big)
    return pd.DataFrame(rows, columns=["rule", "n", "exp_bps", "win", "t", "first_bps", "second_bps", "sym_pos"])


# ----------------------------------------------------------------------------- 实时提示

def _rule_text(rules: list[dict] | None, prefix: str, default: str) -> str:
    for r in rules or []:
        if r.get("rule", "").startswith(prefix):
            return f"历史平均每次 {r['exp'] / 100:+.2f}%，胜率 {r['win']:.0f}%，共 {r['n']} 次"
    return default


def advise_overnight(move: float, hm: int, rules: list[dict] | None = None) -> str:
    """move：合约相对昨天港股收盘的涨跌；hm：当前香港时间（分钟）。"""
    pre_open = 8 * 60 + 55 <= hm < 9 * 60 + 30
    if move > 0.02:
        stats = _rule_text(rules, "夜里涨 >2.0%", "历史平均每次约 +1.4%，胜率约 7 成")
        if pre_open:
            return (f"做空信号：合约比收盘已涨 {move:+.2%}，夜里涨的开盘时平均吐回一半。现在（08:59 前后）做空，"
                    f"09:31 平；09:31 若合约仍比正股贵 0.3% 以上就拿到 11:59（{stats}）。千万别追多")
        return f"合约比收盘涨 {move:+.2%}：若到 08:59 仍涨超过 2%，08:59 做空、09:31 平（{stats}）"
    if move > 0.01:
        stats = _rule_text(rules, "夜里涨 1%~2%", "历史平均每次约 +0.3%，最近一个半月接近不赚")
        if pre_open:
            return f"弱做空信号：合约比收盘涨 {move:+.2%}，1%~2% 这一档优势很薄（{stats}），轻仓或不做；别追多"
        return f"合约比收盘涨 {move:+.2%}：到 08:59 涨超 2% 才是可靠的做空信号，1%~2% 优势很薄（{stats}）"
    if move < -0.01:
        stats = _rule_text(rules, "对照：夜里跌 >1%：08:59 追空", "08:59 追空到 09:31 历史 10 次亏 7 次")
        return (f"合约比收盘跌 {move:+.2%}：夜里跌的通常是真的，不要抄底；也别在开盘前追空，"
                f"09:30 开盘那一下平均反弹约 0.4%（{stats}）")
    return f"合约比收盘 {move:+.2%}，在 ±1% 内，开盘前没有信号"


def advise_baba(move: float, th: float = 0.005) -> str:
    if move > th:
        return f"阿里美股合约夜里涨 {move:+.2%}：开盘后（09:31）偏多，可顺势做多到 11:59（较弱）"
    if move < -th:
        return f"阿里美股合约夜里跌 {move:+.2%}：开盘后（09:31）偏空，可顺势做空到 11:59（较弱）"
    return f"阿里美股合约夜里 {move:+.2%}，中概夜盘没有明显方向"


def reference_close(now: pd.Timestamp) -> pd.Timestamp:
    """当前时刻对应的“上一次港股收盘”日期（香港时间）。16:10 之后算当天，周末和周一开盘前算上周五。"""
    d = now.normalize()
    if now.weekday() < 5 and now.hour * 60 + now.minute >= 16 * 60 + 10:
        return d
    d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d
