"""研究G｜退出规则：主线一旦确认，用什么规则退出能保住最多超额？

第一轮（研究A）的结论是：主线的难点不在“认出来”，而在“退出来”——看到拥挤信号后还有中位 +25% 超额，
但拿到退潮底部平均反而跑输。这里把“退出”做成可交易、可比较的规则：

- 入场（t 日可观测，同一行业 120 日内只入场一次）：
  E1 强势确认：60 日超额排名前 3 且 ≥15%；E2 拥挤确认：成交占比到 3 年 95% 分位且 60 日超额 ≥10%。
- 评估窗口：入场后 250 日。按规则持有行业、退出后持有市场（超额=0），累计相对收益 = 行业/市场 − 1。
- 所有退出信号在 t 日收盘确认，t+entry_lag 日收盘执行。
- 每条规则与“固定持有 120 日”配对比较（同一笔入场），按日期簇自助法给 CI 和 p 值，BH 校正。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import returns as R
from ..core import stats
from ..core.events import condition_events
from ..report import StudyResult, pct
from .common import Panels


def entry_signals(P: Panels) -> dict[str, pd.DataFrame]:
    c = P.cfg["exit"]
    e1 = (P.rank60 <= c["entry_rank"]) & (P.exc60 >= c["entry_min_exc60"])
    e2 = (P.share_pct >= c["entry_crowd_pct"]) & (P.exc60 >= c["entry_crowd_exc60"])
    return {"E1 强势确认": e1, "E2 拥挤确认": e2}


def exit_rules(P: Panels) -> dict[str, pd.DataFrame | int]:
    """返回 {规则名: 宽表布尔信号 或 固定持有天数}。信号为真 = 当日收盘确认退出。"""
    c = P.cfg["exit"]
    close = P.data.sector_close
    rs = P.rs
    rules: dict[str, pd.DataFrame | int] = {}
    for n in c["fixed_hold"]:
        rules[f"固定持有{n}日"] = int(n)
    for x in c["rs_trail"]:
        rules[f"相对强弱回撤{x:.0%}"] = ("trail", float(x))
    for n in c["ma_exit"]:
        below = close < close.rolling(n).mean()
        rules[f"连续2日跌破{n}日线"] = below & below.shift(1, fill_value=False)
    below = rs < rs.rolling(c["rs_ma"]).mean()
    rules[f"相对强弱跌破{c['rs_ma']}日均线"] = below & below.shift(1, fill_value=False)
    rules["成交占比回落"] = ("share", float(c["share_fall_pct"]))
    ret = P.ret
    rules[f"大跌{c['crash_drop']:.0%}且次日续跌"] = (ret.shift(1) <= -c["crash_drop"]) & (ret < 0)
    rules[f"持有满{c['window']}日"] = int(c["window"])
    return rules


def simulate(P: Panels, code: str, t_sig: int, rules: dict, lag: int, window: int) -> dict | None:
    """一笔入场在各规则下的结果。t_sig = 入场信号日位置。"""
    n = len(P.data.dates)
    t0 = t_sig + lag
    end = t0 + window
    if end >= n:
        return None
    rs = P.rs[code].to_numpy(dtype=float)
    if not (np.isfinite(rs[t0]) and np.isfinite(rs[end])):
        return None
    share_pct = P.share_pct[code].to_numpy(dtype=float)
    path = rs[t0:end + 1] / rs[t0]
    out = {"_max": float(np.nanmax(path) - 1), "_end": float(path[-1] - 1)}
    for name, rule in rules.items():
        if isinstance(rule, int):
            s_exit = min(t0 + rule, end)
        elif isinstance(rule, tuple) and rule[0] == "trail":
            peak = np.maximum.accumulate(np.nan_to_num(path, nan=1.0))
            hit = np.flatnonzero(path[1:] <= (1 - rule[1]) * peak[1:])
            s_exit = min(t0 + 1 + int(hit[0]) + lag, end) if len(hit) else end
        elif isinstance(rule, tuple) and rule[0] == "share":
            sp = share_pct[t0:end + 1]
            reached = np.maximum.accumulate(np.nan_to_num(sp, nan=0.0) >= P.cfg["exit"]["entry_crowd_pct"])
            hit = np.flatnonzero(reached[1:] & (sp[1:] < rule[1]))
            s_exit = min(t0 + 1 + int(hit[0]) + lag, end) if len(hit) else end
        else:
            sig = rule[code].to_numpy(dtype=bool)[t0 + 1:end + 1]
            hit = np.flatnonzero(sig)
            s_exit = min(t0 + 1 + int(hit[0]) + lag, end) if len(hit) else end
        out[name] = float(rs[s_exit] / rs[t0] - 1)
        out[name + "#天数"] = int(s_exit - t0)
    return out


def run(P: Panels) -> StudyResult:
    c = P.cfg["exit"]
    cc = P.cfg["common"]
    res = StudyResult("G", "退出规则", "主线一旦确认，用什么规则退出能保住最多超额？", meta=P.meta())
    rules = exit_rules(P)
    base = c["baseline"]
    res.definitions = [
        f"E1 强势确认：60 日超额排名前 {c['entry_rank']} 且 ≥{c['entry_min_exc60']:.0%}；"
        f"E2 拥挤确认：成交占比到自身 3 年 {c['entry_crowd_pct']:.0%} 分位且 60 日超额 ≥{c['entry_crowd_exc60']:.0%}；"
        f"同一行业 {c['entry_gap']} 个交易日内只入场一次",
        f"评估窗口：入场后 {c['window']} 日；退出后持有市场；指标 = 持有期相对收益（行业/市场−1）",
        f"入场与退出都在信号日后第 {P.lag} 个交易日收盘执行（与全部研究一致）",
        "退出规则：" + "、".join(rules.keys()),
        f"配对比较：同一笔入场，规则 − {base}；p 值为按日期簇自助法（相隔 ≤20 日的入场归为一簇），BH 校正",
        "“事后最大可得”= 窗口内相对收益的最高点（不可实现，只作天花板）",
    ]
    dates = P.data.dates
    rows = []
    for ename, sig in entry_signals(P).items():
        for code in sig.columns:
            for d in condition_events(sig[code], int(c["entry_gap"])):
                if not (P.study_start <= d <= P.study_end):
                    continue
                t = int(dates.get_loc(d))
                r = simulate(P, code, t, rules, P.lag, int(c["window"]))
                if r is not None:
                    rows.append({"入场": ename, "行业": P.data.name(code), "代码": code, "date": d, **r})
    trades = pd.DataFrame(rows)
    if trades.empty:
        res.findings.append("没有完整的 250 日窗口的入场样本。")
        return res

    rule_names = list(rules.keys())
    summary, tests = [], []
    for ename, tr in trades.groupby("入场", sort=False):
        tr = tr.reset_index(drop=True)
        cl = stats.date_clusters(tr["date"], int(c.get("cluster_gap", 20)), dates)
        first = (tr["date"] <= P.split).to_numpy()
        for rn in rule_names:
            v = tr[rn].to_numpy(dtype=float)
            summary.append({"入场": ename, "规则": rn, "笔数": len(v), "相对收益均值": v.mean(), "中位": np.median(v),
                            "胜率": float(np.mean(v > 0)), "平均持有(日)": tr[rn + "#天数"].mean(),
                            "捕获率(相对最大可得)": float(np.mean(v) / np.mean(tr["_max"])) if tr["_max"].mean() > 0 else np.nan})
            if rn == base:
                continue
            dlt = v - tr[base].to_numpy(dtype=float)
            cb = stats.cluster_bootstrap(lambda ix, x=dlt: float(np.mean(x[ix])), cl, n_boot=cc["n_boot"], rng=P.rng)
            d1, d2 = dlt[first].mean() if first.any() else np.nan, dlt[~first].mean() if (~first).any() else np.nan
            tests.append({"入场": ename, "规则": rn, "笔数": len(dlt), "独立簇": int(len(np.unique(cl))),
                          f"相对{base}的差": float(dlt.mean()), "90%CI低": cb["lo"], "90%CI高": cb["hi"], "p值": cb["p"],
                          "占优比例": float(np.mean(dlt > 0)), "前段差": d1, "后段差": d2,
                          "两段同向": bool(np.isfinite(d1) and np.isfinite(d2) and d1 * d2 > 0)})
    summ = pd.DataFrame(summary)
    tt = pd.DataFrame(tests)
    tt["q值"] = stats.bh_adjust(tt["p值"].to_numpy())
    tt["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q, bool(cs), P.grade_rule)]
                 for n, q, cs in zip(tt["独立簇"], tt["q值"], tt["两段同向"])]
    ceil = trades.groupby("入场")[["_max", "_end"]].mean().rename(columns={"_max": "事后最大可得均值", "_end": f"持有满{c['window']}日均值"})

    res.add("各退出规则的表现（每笔入场在 250 日窗口内的相对收益）", summ,
            "捕获率 = 规则的平均相对收益 / 事后最大可得的平均值。",
            pct_cols=["相对收益均值", "中位", "胜率", "捕获率(相对最大可得)"])
    res.add(f"与“{base}”配对比较（同一笔入场）", tt,
            pct_cols=[f"相对{base}的差", "90%CI低", "90%CI高", "占优比例", "前段差", "后段差"])
    res.add("天花板：事后最大可得", ceil.reset_index(), pct_cols=list(ceil.columns))
    show = trades[["入场", "行业", "date", "_max", "_end", *rule_names]].rename(columns={"date": "入场信号日", "_max": "事后最大可得", "_end": "持有满窗口"})
    # 诊断（事后、不可交易）：入场后来是否真的成了研究A意义上的主线
    from .a_lifecycle import detect_episodes
    ep = detect_episodes(P)
    if not ep.empty:
        def in_mainline(code, d):
            t = int(dates.get_loc(d))
            sub = ep[(ep["代码"] == code) & ep["_start"].notna()]
            return bool(((sub["_start"] <= t) & (t <= sub["_top"])).any())
        trades["事后成为主线"] = [in_mainline(c_, d) for c_, d in zip(trades["代码"], trades["date"])]
        diag = trades.groupby(["入场", "事后成为主线"]).agg(
            笔数=(base, "size"), 固定持有120日均值=(base, "mean"), 持有满窗口均值=("_end", "mean"),
            事后最大可得均值=("_max", "mean")).reset_index()
        diag["占比"] = diag["笔数"] / diag.groupby("入场")["笔数"].transform("sum")
        res.add("诊断：按“事后是否成为主线”拆分入场（用了未来信息，不可交易）", diag,
                "说明研究A的“信号后还剩多少超额”为什么不能直接当交易预期：那是只统计了事后成为主线的样本。",
                pct_cols=["固定持有120日均值", "持有满窗口均值", "事后最大可得均值", "占比"])
        for ename, sub in diag.groupby("入场"):
            yes = sub[sub["事后成为主线"]]
            no = sub[~sub["事后成为主线"]]
            if len(yes) and len(no):
                res.findings.append(
                    f"诊断（事后）：{ename} 的入场中 {pct(yes['占比'].iloc[0], 0)} 事后成了主线，这部分持有满窗口平均 {pct(yes['持有满窗口均值'].iloc[0])}；"
                    f"其余 {pct(no['占比'].iloc[0], 0)} 平均 {pct(no['持有满窗口均值'].iloc[0])}——实时无法区分两者，所以整体接近 0。"
                )
    res.add("逐笔明细", show.sort_values(["入场", "入场信号日"]), pct_cols=[c_ for c_ in show.columns if c_ not in ("入场", "行业", "入场信号日")],
            max_rows=150)

    # ---- 结论 ----
    for ename in trades["入场"].unique():
        s = summ[summ["入场"] == ename].set_index("规则")
        b = s.loc[base]
        best = s["相对收益均值"].idxmax()
        res.findings.append(
            f"{ename}（{int(b['笔数'])} 笔）：{base} 平均相对收益 {pct(b['相对收益均值'])}（胜率 {pct(b['胜率'], 0)}），"
            f"事后最大可得 {pct(ceil.loc[ename, '事后最大可得均值'])}；平均相对收益最高的规则是「{best}」{pct(s.loc[best, '相对收益均值'])}。"
        )
        sub = tt[tt["入场"] == ename]
        good = sub[sub["证据"].str.startswith(("A", "B")) & (sub[f"相对{base}的差"] > 0)]
        bad = sub[sub["证据"].str.startswith(("A", "B")) & (sub[f"相对{base}的差"] < 0)]
        if len(good):
            res.findings.append(f"{ename}：显著优于{base}的规则——" + "；".join(
                f"{r['规则']}（+{r[f'相对{base}的差'] * 100:.1f}pp，{r['证据']}）" for _, r in good.iterrows()))
        if len(bad):
            res.findings.append(f"{ename}：显著差于{base}的规则——" + "；".join(
                f"{r['规则']}（{r[f'相对{base}的差'] * 100:.1f}pp，{r['证据']}）" for _, r in bad.iterrows()))
        if not len(good) and not len(bad):
            res.findings.append(f"{ename}：没有任何退出规则与{base}有显著差别（均低于 B 级）。")
    for h, rn in (("H-G1", "相对强弱回撤15%"), ("H-G2", f"大跌{c['crash_drop']:.0%}且次日续跌"), ("H-G3", "成交占比回落")):
        sub = tt[tt["规则"] == rn]
        if not sub.empty:
            res.findings.append(f"{h}（{rn} 优于{base}）：" + "；".join(
                f"{r['入场']} 差 {pct(r[f'相对{base}的差'])}，p={r['p值']:.3f}，{r['证据']}" for _, r in sub.iterrows()))
    res.caveats = [
        "入场信号本身是否有超额不在本研究范围内（见研究A/B），这里只比较“同一笔入场”下不同退出方式的差别。",
        "退出后视为持有市场、再入场要等下一次信号；现实中可能会换到别的主线，收益会不同。",
        "指数层面，未计入交易成本（各规则换手次数相同：一进一出）。",
    ]
    return res
