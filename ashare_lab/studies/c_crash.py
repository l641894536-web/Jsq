"""研究C｜主线大跌：强势板块单日 −5%/−7%/−10% 以后，什么时候是机会，什么时候是趋势结束？

方法：
1. 强势板块（t-1 日可知）：60 日超额收益排名前 5 且 60 日超额 ≥ 10%。
2. 大跌事件：强势板块当日跌幅 ≥ 5%/7%/10%；另做波动率标准化版本（跌幅 ≥ 3σ/4σ）。
   同一行业 10 日内的连续大跌合并为一个事件。
3. 结果分类（事后）：
   - 机会：20 日内收复大跌前收盘价，且 20 日超额 > 0；
   - 趋势结束：60 日内相对强弱没有再创新高，且 60 日超额 < 0；
   - 其余：中性。
4. 对照：同一行业“强势但没大跌”的随机日——大跌后的表现要和“本来就强”区分开。
5. 区分机会/结束的特征全部是大跌当天收盘前可观测的（大跌前涨幅、是否放量、市场是否同步大跌、
   是否拥挤、距离均线、近期是否已经大跌过……），逐个做分组对比 + Fisher 检验 + BH 校正。
   样本少，不做机器学习——只做单变量，结论才不会被过拟合。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import returns as R
from ..core import stats
from ..core.events import concat_events, condition_events, events_frame, restrict_dates
from ..core.eventstudy import add_grades, event_study, lookup
from ..report import StudyResult, pct
from .common import Panels

OPP, END, NEUTRAL = "机会", "趋势结束", "中性"


def strong_mask(P: Panels) -> pd.DataFrame:
    c = P.cfg["crash"]
    return ((P.rank60 <= c["strong_top_k"]) & (P.exc60 >= c["strong_min_exc60"])).shift(1, fill_value=False)


def build_events(P: Panels) -> pd.DataFrame:
    """所有口径的大跌事件（含特征与结果），一行一个 (口径, 日期, 行业)。"""
    c = P.cfg["crash"]
    ret = P.ret
    strong = strong_mask(P)
    sigma = ret.rolling(20, min_periods=15).std().shift(1)
    defs = [(f"跌幅≥{th:.0%}", ret <= -th) for th in c["drop_thresholds"]]
    defs += [(f"跌幅≥{k:g}σ", ret <= -k * sigma) for k in c["sigma_multiples"]]
    frames = []
    for label, cond in defs:
        m = cond & strong
        per = {code: condition_events(m[code], c["min_gap_days"]) for code in m.columns}
        frames.append(events_frame(per, 口径=label))
    ev = restrict_dates(concat_events(frames), P.study_start, P.study_end)
    if ev.empty:
        return ev
    return add_features_outcomes(P, ev)


def add_features_outcomes(P: Panels, ev: pd.DataFrame) -> pd.DataFrame:
    c = P.cfg["crash"]
    close = P.data.sector_close
    amount = P.data.sector_amount
    rs = P.rs
    ret = P.ret
    dates = P.data.dates
    feats = {
        "当日跌幅": ret,
        "当日超额": R.excess(ret, P.mret),
        "前20日涨幅": R.past_return(close, 20).shift(1),
        "前60日超额": P.exc60.shift(1),
        "放量倍数": amount / amount.rolling(20, min_periods=15).mean().shift(1),
        "成交占比分位": P.share_pct.shift(1),
        "偏离20日线": (close / close.rolling(20).mean() - 1).shift(1),
        "距RS高点天数": rs.rolling(60, min_periods=20).apply(lambda a: len(a) - 1 - int(np.nanargmax(a)), raw=True).shift(1),
        "前60日大跌次数": (ret <= -min(c["drop_thresholds"])).astype(float).rolling(60, min_periods=1).sum().shift(1),
    }
    mret = P.mret
    out = ev.copy()
    for name, panel in feats.items():
        out[name] = lookup(panel, out)
    out["市场当日涨跌"] = [mret.get(d, np.nan) for d in out["date"]]

    # 结果：lag=0（大跌当日收盘买入）为主，lag=1 为稳健性
    rd, ed = c["recover_days"], c["end_days"]
    for lag in (0, 1):
        for h in P.horizons:
            out[f"L{lag}_{h}日超额"] = lookup(P.fwd_exc(h, lag), out)
            out[f"L{lag}_{h}日收益"] = lookup(P.fwd_ret(h, lag), out)
    prev_close = close.shift(1)
    recovered = (R.fwd_max(close, rd, 0) >= prev_close)
    rs_prior_high = rs.rolling(60, min_periods=20).max().shift(1)
    new_high = (R.fwd_max(rs, ed, 0) > rs_prior_high)
    out[f"{rd}日内收复"] = lookup(recovered.astype(float).where(R.fwd_max(close, rd, 0).notna()), out)
    out[f"{ed}日内RS新高"] = lookup(new_high.astype(float).where(R.fwd_max(rs, ed, 0).notna()), out)
    exc_r = out[f"L0_{rd}日超额"] if f"L0_{rd}日超额" in out else lookup(P.fwd_exc(rd, 0), out)
    exc_e = out[f"L0_{ed}日超额"] if f"L0_{ed}日超额" in out else lookup(P.fwd_exc(ed, 0), out)
    label = np.full(len(out), NEUTRAL, dtype=object)
    opp = (out[f"{rd}日内收复"] == 1) & (exc_r > 0)
    end = (out[f"{ed}日内RS新高"] == 0) & (exc_e < 0)
    label[opp.to_numpy()] = OPP
    label[end.to_numpy() & ~opp.to_numpy()] = END
    unknown = out[f"{ed}日内RS新高"].isna() | pd.isna(exc_e)
    label[unknown.to_numpy()] = "未知(数据不足)"
    out["结果"] = label
    # 修正口径（第三轮）：结果从次日收盘之后开始计，不含次日本身的涨跌。
    # 用于“次日确认”类检验——否则次日续跌会机械地拉低之后的超额、让“趋势结束”更容易成立。
    rec1 = (R.fwd_max(close, rd, 1) >= prev_close).astype(float).where(R.fwd_max(close, rd, 1).notna())
    nh1 = (R.fwd_max(rs, ed, 1) > rs_prior_high).astype(float).where(R.fwd_max(rs, ed, 1).notna())
    rec1_v, nh1_v = lookup(rec1, out), lookup(nh1, out)
    exc_r1, exc_e1 = out[f"L1_{rd}日超额"].to_numpy(), out[f"L1_{ed}日超额"].to_numpy()
    label1 = np.full(len(out), NEUTRAL, dtype=object)
    opp1 = (rec1_v == 1) & (exc_r1 > 0)
    end1 = (nh1_v == 0) & (exc_e1 < 0)
    label1[opp1] = OPP
    label1[end1 & ~opp1] = END
    label1[np.isnan(nh1_v) | np.isnan(exc_e1)] = "未知(数据不足)"
    out["结果(次日后)"] = label1
    # 次日确认（t+1 日才知道）
    nxt = ret.shift(-1)
    out["次日涨跌"] = lookup(nxt, out)
    out["行业"] = [P.data.name(k) for k in out["key"]]
    return out


def _nextday_row(main: pd.DataFrame, col: str, name: str, P: Panels, cc: dict) -> dict | None:
    known = main[main[col].isin([OPP, END, NEUTRAL]) & main["次日涨跌"].notna()].reset_index(drop=True)
    if len(known) < 10:
        return None
    y = (known[col] == END).to_numpy(dtype=float)
    dn = (known["次日涨跌"] < 0).to_numpy()
    cl = stats.date_clusters(known["date"], 10, P.data.dates)

    def gap(ix):
        a, b = y[ix][dn[ix]], y[ix][~dn[ix]]
        return float(a.mean() - b.mean()) if len(a) >= 2 and len(b) >= 2 else np.nan

    cb = stats.cluster_bootstrap(gap, cl, n_boot=cc["n_boot"], rng=P.rng)
    first = (known["date"] <= P.split).to_numpy()
    g1, g2 = gap(np.flatnonzero(first)), gap(np.flatnonzero(~first))
    cons = bool(np.isfinite(g1) and np.isfinite(g2) and g1 * g2 > 0)
    k = cb["clusters"]
    return {"检验": name, "差值": cb["stat"], "90%CI低": cb["lo"], "90%CI高": cb["hi"], "p值": cb["p"], "独立簇": k,
            "前段差": g1, "后段差": g2, "两段同向": cons,
            "证据": stats.GRADE_TEXT[stats.evidence_grade(k, cb["p"], cons, P.grade_rule)] if np.isfinite(cb["p"]) else ""}


def feature_splits(ev: pd.DataFrame, features: list[str], rule, split, calendar, n_boot: int = 2000, rng=None) -> pd.DataFrame:
    """每个特征按中位数分两组：趋势结束比例、机会比例、60日超额均值。

    p 值用“按日期簇自助法”（同一天/同一波下跌里的多个行业只算一份证据），比 Fisher 检验保守；
    前后两段分别计算“高组−低组”的趋势结束比例差，方向一致才可能给到 A/B 级。
    """
    e = ev[ev["结果"].isin([OPP, END, NEUTRAL])].reset_index(drop=True)
    if e.empty:
        return pd.DataFrame()
    first = e["date"] <= split
    clusters = stats.date_clusters(e["date"], 10, calendar)
    is_end = (e["结果"] == END).astype(float).to_numpy()
    rows = []
    for f in features:
        x = e[f]
        ok = x.notna()
        if ok.sum() < 6:
            continue
        med = x[ok].median()
        hi = e[ok & (x > med)]
        lo = e[ok & (x <= med)]
        k1, n1 = int((hi["结果"] == END).sum()), len(hi)
        k2, n2 = int((lo["结果"] == END).sum()), len(lo)
        cb = stats.cluster_bootstrap_diff(is_end[ok.to_numpy()], (x[ok] > med).to_numpy(), clusters[ok.to_numpy()],
                                          n_boot=n_boot, rng=rng)
        rows.append({
            "特征": f, "分界(中位数)": med,
            "高组n": n1, "高组趋势结束比例": k1 / n1 if n1 else np.nan, "高组机会比例": (hi["结果"] == OPP).mean() if n1 else np.nan,
            "高组60日超额": hi["L0_60日超额"].mean() if "L0_60日超额" in hi else np.nan,
            "低组n": n2, "低组趋势结束比例": k2 / n2 if n2 else np.nan, "低组机会比例": (lo["结果"] == OPP).mean() if n2 else np.nan,
            "低组60日超额": lo["L0_60日超额"].mean() if "L0_60日超额" in lo else np.nan,
            "结束比例差90%CI": f"{cb['lo'] * 100:.0f}%~{cb['hi'] * 100:.0f}%" if np.isfinite(cb["lo"]) else "",
            "p值": cb["p"],
            "Fisher p(不计聚集)": stats.fisher_p(k1, n1, k2, n2),
            "前段差": _end_gap(e[first & ok], x[first & ok] > med),
            "后段差": _end_gap(e[~first & ok], x[~first & ok] > med),
            "独立簇": int(len(np.unique(clusters[ok.to_numpy()]))),
        })
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["q值"] = stats.bh_adjust(t["p值"].to_numpy())
    t["两段同向"] = [bool(np.isfinite(a) and np.isfinite(b) and a * b > 0) for a, b in zip(t["前段差"], t["后段差"])]
    t["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q, c_, rule)] for n, q, c_ in zip(t["独立簇"], t["q值"], t["两段同向"])]
    return t


def _end_gap(e: pd.DataFrame, is_hi: pd.Series) -> float:
    hi, lo = e[is_hi], e[~is_hi]
    if len(hi) == 0 or len(lo) == 0:
        return np.nan
    return float((hi["结果"] == END).mean() - (lo["结果"] == END).mean())


def run(P: Panels) -> StudyResult:
    c = P.cfg["crash"]
    cc = P.cfg["common"]
    res = StudyResult("C", "主线大跌", "强势板块单日 −5%/−7%/−10% 以后，什么时候是机会，什么时候是趋势结束？", meta=P.meta())
    res.definitions = [
        f"强势板块：前一交易日 60 日超额收益排名前 {c['strong_top_k']} 且 60 日超额 ≥ {c['strong_min_exc60']:.0%}",
        f"大跌：当日跌幅 ≥ {'/'.join(f'{x:.0%}' for x in c['drop_thresholds'])}，或 ≥ {'/'.join(f'{x:g}' for x in c['sigma_multiples'])} 倍 20 日波动率；"
        f"同一行业 {c['min_gap_days']} 日内的连续大跌算一个事件",
        f"机会：{c['recover_days']} 日内收复大跌前收盘价，且 {c['recover_days']} 日超额 > 0",
        f"趋势结束：{c['end_days']} 日内相对强弱未创大跌前 60 日新高，且 {c['end_days']} 日超额 < 0",
        "结果以“大跌当日收盘买入”(L0) 为主，“次日收盘买入”(L1) 做稳健性对照",
        "对照：同一行业“强势但没有大跌”的随机日（置换检验）",
    ]
    ev = build_events(P)
    if ev.empty:
        res.findings.append("研究区间内没有符合条件的强势板块大跌事件。")
        return res
    strong = strong_mask(P)

    # 1) 事件研究：大跌 vs 强势不跌
    rows = []
    for label, sub in ev.groupby("口径", sort=False):
        e2 = sub[["date", "key"]].reset_index(drop=True)
        metrics = {f"{h}日超额(L0)": P.fwd_exc(h, 0) for h in P.horizons}
        t = event_study(e2, metrics, strong, P.split, cc["n_perm"], cc["n_boot"], P.rng, period=P.period)
        t.insert(0, "口径", label)
        rows.append(t)
    es = add_grades(pd.concat(rows, ignore_index=True), P.grade_rule)
    es_l1 = []
    for label, sub in ev.groupby("口径", sort=False):
        for h in P.horizons:
            v = sub[f"L1_{h}日超额"].dropna()
            es_l1.append({"口径": label, "期限": h, "n": len(v), "L1超额均值": v.mean() if len(v) else np.nan})
    es_l1 = pd.DataFrame(es_l1)

    # 2) 结果分布
    out_rows = []
    for label, sub in ev.groupby("口径", sort=False):
        known = sub[sub["结果"] != "未知(数据不足)"]
        n = len(known)
        row = {"口径": label, "事件数": len(sub), "可判定": n}
        for k in (OPP, NEUTRAL, END):
            cnt = int((known["结果"] == k).sum())
            lo, hi = stats.wilson_ci(cnt, n)
            row[f"{k}比例"] = cnt / n if n else np.nan
            row[f"{k}90%CI"] = f"{pct(lo, 0)}~{pct(hi, 0)}" if n else ""
        out_rows.append(row)
    outcome = pd.DataFrame(out_rows)

    # 3) 特征分组（以最宽口径“跌幅≥最小阈值”为主样本）
    base_label = f"跌幅≥{min(c['drop_thresholds']):.0%}"
    main = ev[ev["口径"] == base_label]
    features = ["当日跌幅", "当日超额", "市场当日涨跌", "前20日涨幅", "前60日超额", "放量倍数", "成交占比分位",
                "偏离20日线", "距RS高点天数", "前60日大跌次数"]
    splits = feature_splits(main, features, P.grade_rule, P.split, P.data.dates, cc["n_boot"], P.rng)

    # 4) 次日确认
    nd_rows = []
    for tag, m in (("次日收涨", main["次日涨跌"] >= 0), ("次日续跌", main["次日涨跌"] < 0)):
        sub = main[m & main["结果"].isin([OPP, END, NEUTRAL])]
        nd_rows.append({"次日": tag, "n": len(sub), "趋势结束比例": (sub["结果"] == END).mean() if len(sub) else np.nan,
                        "机会比例": (sub["结果"] == OPP).mean() if len(sub) else np.nan,
                        "L1_20日超额均值": sub["L1_20日超额"].mean() if len(sub) else np.nan,
                        "L1_60日超额均值": sub["L1_60日超额"].mean() if len(sub) else np.nan})
    nd = pd.DataFrame(nd_rows)
    main_known = main[main["结果"].isin([OPP, END, NEUTRAL])].reset_index(drop=True)
    nd_cb = stats.cluster_bootstrap_diff((main_known["结果"] == END).astype(float).to_numpy(),
                                         (main_known["次日涨跌"] < 0).to_numpy(),
                                         stats.date_clusters(main_known["date"], 10, P.data.dates), n_boot=cc["n_boot"], rng=P.rng)
    fixed_row = _nextday_row(main, "结果(次日后)", "修正口径：结果从次日收盘之后计（第三轮）", P, cc)
    k1 = int(((main["次日涨跌"] >= 0) & (main["结果"] == END)).sum())
    n1 = int(((main["次日涨跌"] >= 0) & main["结果"].isin([OPP, END, NEUTRAL])).sum())
    k2 = int(((main["次日涨跌"] < 0) & (main["结果"] == END)).sum())
    n2 = int(((main["次日涨跌"] < 0) & main["结果"].isin([OPP, END, NEUTRAL])).sum())
    nd_p = nd_cb["p"]
    firsth = (main_known["date"] <= P.split).to_numpy()
    gaps = []
    for m_ in (firsth, ~firsth):
        sub = main_known[m_]
        down, up = sub[sub["次日涨跌"] < 0], sub[sub["次日涨跌"] >= 0]
        gaps.append(float((down["结果"] == END).mean() - (up["结果"] == END).mean()) if len(down) and len(up) else np.nan)
    nd_ncl = int(len(np.unique(stats.date_clusters(main_known["date"], 10, P.data.dates)))) if len(main_known) else 0
    nd_cons = bool(np.isfinite(gaps[0]) and np.isfinite(gaps[1]) and gaps[0] * gaps[1] > 0)
    nd_test = pd.DataFrame([{
        "检验": "次日续跌 − 次日收涨 的趋势结束比例差", "差值": nd_cb["diff"],
        "90%CI低": nd_cb["lo"], "90%CI高": nd_cb["hi"], "p值": nd_p, "独立簇": nd_ncl,
        "前段差": gaps[0], "后段差": gaps[1], "两段同向": nd_cons,
        "证据": stats.GRADE_TEXT[stats.evidence_grade(nd_ncl, nd_p, nd_cons, P.grade_rule)] if np.isfinite(nd_p) else "",
    }])
    if fixed_row is not None:
        nd_test = pd.concat([nd_test, pd.DataFrame([fixed_row])], ignore_index=True)

    # ---- 表格 ----
    res.add("大跌后 vs 强势不跌的随机日（L0：大跌当日收盘买入）",
            es[["口径", "指标", "n", "独立簇", "均值", "中位数", "胜率", "基准均值", "差值", "均值90%CI低", "均值90%CI高", "p值", "q值",
                "前段n", "后段n", "两段同向", "证据"]],
            "基准 = 同一行业在“强势且没有大跌”的日子买入的平均超额。")
    res.add("稳健性：次日收盘买入（L1）的平均超额", es_l1)
    res.add("结果分布：机会 / 中性 / 趋势结束", outcome)
    if not splits.empty:
        res.add(f"哪些特征能区分“机会”和“趋势结束”（样本：{base_label}）", splits,
                "按特征中位数分高/低两组；p 值为两组“趋势结束比例”之差的按日期簇自助法检验（同一波下跌里的多个行业只算一份证据），"
                "Fisher p 仅供对照（假设事件独立，偏乐观）；q 值为 BH 校正；"
                "前段差/后段差 = 高组−低组的趋势结束比例（分前后两段计算）。",
                pct_cols=[c_ for c_ in splits.columns if ("比例" in c_ and "CI" not in c_) or "超额" in c_ or c_ in ("前段差", "后段差")])
    res.add("次日确认：大跌次日收涨 vs 续跌（t+1 才知道）", nd)
    res.add("次日确认的检验（按日期簇自助法；单项检验，不做多重校正）", nd_test,
            pct_cols=["差值", "90%CI低", "90%CI高", "前段差", "后段差"])
    detail_cols = ["口径", "date", "行业", "当日跌幅", "市场当日涨跌", "前60日超额", "放量倍数", "成交占比分位", "距RS高点天数",
                   "前60日大跌次数", "次日涨跌", "L0_20日超额", "L0_60日超额", f"{c['recover_days']}日内收复", "结果"]
    res.add("事件明细", ev[detail_cols].rename(columns={"date": "日期"}).sort_values(["口径", "日期"]), max_rows=300)

    # ---- 结论 ----
    for label in [f"跌幅≥{th:.0%}" for th in c["drop_thresholds"]]:
        sub = es[es["口径"] == label]
        oc = outcome[outcome["口径"] == label]
        if sub.empty or oc.empty:
            res.findings.append(f"{label}：研究区间内强势板块没有出现过，无法检验。")
            continue
        r20 = sub[sub["指标"] == "20日超额(L0)"]
        r60 = sub[sub["指标"] == f"{max(P.horizons)}日超额(L0)"]
        o = oc.iloc[0]
        ncl = int(sub["独立簇"].max()) if "独立簇" in sub else 0
        txt = (f"{label}（事件 {int(o['事件数'])} 个，{ncl} 个独立簇）：机会 {pct(o[f'{OPP}比例'], 0)} / 中性 {pct(o[f'{NEUTRAL}比例'], 0)} / "
               f"趋势结束 {pct(o[f'{END}比例'], 0)}")
        if not r20.empty:
            r = r20.iloc[0]
            txt += f"；20日超额 {pct(r['均值'])} vs 强势不跌 {pct(r['基准均值'])}（{r['证据']}）"
        if not r60.empty:
            r = r60.iloc[0]
            txt += f"；{max(P.horizons)}日超额 {pct(r['均值'])} vs {pct(r['基准均值'])}（{r['证据']}）"
        res.findings.append(txt + "。")
    if not splits.empty:
        sig = splits[splits["证据"].str.startswith(("A", "B"))]
        if sig.empty:
            top = splits.nsmallest(3, "p值")
            res.findings.append(
                "没有任何单一特征能在统计上可靠地区分“机会”和“趋势结束”（全部低于 B 级）。p 值最小的几个特征："
                + "；".join(f"{r['特征']}（高组结束率 {pct(r['高组趋势结束比例'], 0)} vs 低组 {pct(r['低组趋势结束比例'], 0)}，p={r['p值']:.3f}）"
                            for _, r in top.iterrows()) + "——只能作为观察线索。"
            )
        else:
            for _, r in sig.iterrows():
                res.findings.append(
                    f"特征“{r['特征']}”有区分度：高于 {r['分界(中位数)']:.3g} 时趋势结束比例 {pct(r['高组趋势结束比例'], 0)}，"
                    f"低于时 {pct(r['低组趋势结束比例'], 0)}（q={r['q值']:.3f}，{r['证据']}）。"
                )
    if n1 and n2:
        res.findings.append(
            f"次日确认：大跌次日收涨的趋势结束比例 {pct(k1 / n1, 0)}（n={n1}），次日续跌 {pct(k2 / n2, 0)}（n={n2}），"
            f"按簇自助法 p={nd_p:.3f}，前段差 {pct(gaps[0], 0)}/后段差 {pct(gaps[1], 0)}（{nd_test.iloc[0]['证据']}）。"
        )
    if fixed_row is not None:
        res.findings.append(
            f"次日确认（修正口径，结果从次日收盘之后计，排除次日本身的机械影响）：差值 {pct(fixed_row['差值'], 0)}"
            f"（90%CI {pct(fixed_row['90%CI低'], 0)}~{pct(fixed_row['90%CI高'], 0)}，{fixed_row['证据']}）。"
        )
    res.caveats = [
        "申万一级行业单日 −7%/−10% 极少见（主要集中在 2015—2016 股灾、2024 年初微盘股踩踏），样本量决定了这里大部分结论只能是 C/D 级。"
        "要研究更多样本，可把 sector_daily 换成二级行业或概念板块重跑（大跌更频繁）。",
        "“机会/趋势结束”的标签用到了未来 20/60 日数据，是事后结果，不是信号。",
        "同一天多个强势行业一起大跌（系统性下跌）时事件并不独立，p 值会偏乐观；可看“当日超额”特征区分系统性与行业自身的下跌。",
        "涨跌停和T+1：指数层面的大跌当日收盘买入，个股层面可能因跌停无法成交。",
    ]
    return res
