"""研究D｜风格切换：成长→价值、价值→成长之前有没有可观察的领先信号？

方法：
1. 风格相对线 s = log(成长指数/价值指数)（默认 国证成长/国证价值；另测 小盘/大盘）。
2. 切换点 = s 的 zigzag(10%) 峰/谷，且每段 ≥ 40 个交易日：峰 = 成长→价值，谷 = 价值→成长。
3. 候选领先信号（全部 t 日可观测，用扩展窗口分位数，无前视）：
   相对动量(60/120日)、相对偏离年线、成交额比(成长/价值)的 z 值、成长主题成交拥挤度、
   10年国债收益率 60 日变化、期限利差、市场 60 日动量、相对波动率。
   方向预注册为“信号越高 → 越可能成长→价值”。
4. 三种检验，只有前两种算数：
   (a) 预测力：信号与未来 20/60/120 日风格收益的秩相关 IC，Newey-West t 值（处理重叠）；
   (b) 预警：信号进入极端分位（≥90% 或 ≤10%）后 60 日内发生对应方向切换的比例，
       对比“随便哪天”60 日内发生切换的基准概率（二项检验），并报告召回率；
   (c) 切换前的信号画像——仅描述：因为切换点是按价格事后选出来的，价格类信号在峰前必然偏高，
       这里的“规律”有选择偏差，不能当证据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import returns as R
from ..core import stats
from ..core.events import crossing_events
from ..core.zigzag import filter_short_legs, zigzag
from ..report import StudyResult, pct
from .common import Panels

SIGNAL_DESC = {
    "相对动量60日": "log(成长/价值) 的 60 日变化",
    "相对动量120日": "log(成长/价值) 的 120 日变化",
    "相对偏离年线": "log(成长/价值) 减去其 250 日均值",
    "成交额比z值": "log(成长成交额/价值成交额) 的 250 日 z 值",
    "成长拥挤度": "成长主题组合成交占比的历史分位",
    "国债10Y变化60日": "10 年国债收益率 60 日变化（bp）",
    "期限利差": "10 年 − 2 年国债收益率",
    "市场动量60日": "中证全指 60 日涨幅",
    "相对波动率": "log(成长20日波动/价值20日波动)",
}


def style_ratio(P: Panels, g: str, v: str) -> pd.Series | None:
    ic = P.data.index_close
    if g not in ic or v not in ic:
        return None
    r = (ic[g] / ic[v]).where(lambda x: x > 0)
    if r.notna().sum() < 500:
        return None
    return r


def switch_points(ratio: pd.Series, swing: float, min_days: int, a: str = "成长", b: str = "价值") -> pd.DataFrame:
    piv = zigzag(ratio, swing, log=True)
    if len(piv) >= 3:
        piv = filter_short_legs(piv, ratio, min_days)
    if piv.empty:
        return piv
    piv = piv.reset_index(drop=True).copy()
    piv["方向"] = np.where(piv["kind"] == "peak", f"{a}→{b}", f"{b}→{a}")
    # 合并短波段后重新计算确认日：从拐点起反向走满阈值的第一天
    x = np.log(ratio.to_numpy(dtype=float))
    th = np.log1p(swing)
    conf = []
    for pos, kind in zip(piv["pos"], piv["kind"]):
        after = x[pos + 1:] - x[pos]
        hit = np.flatnonzero(after <= -th) if kind == "peak" else np.flatnonzero(after >= th)
        conf.append(int(pos + 1 + hit[0]) if len(hit) else -1)
    piv["confirm_pos"] = conf
    piv["confirmed"] = piv["confirm_pos"] >= 0
    piv["前一段风格收益"] = piv["value"] / piv["value"].shift(1) - 1
    piv["前一段天数"] = piv["pos"] - piv["pos"].shift(1)
    return piv


def build_signals(P: Panels, g: str, v: str, ratio: pd.Series, primary: bool) -> dict[str, pd.Series]:
    s = np.log(ratio)
    ic, ia = P.data.index_close, P.data.index_amount
    sig = {
        "相对动量60日": s - s.shift(60),
        "相对动量120日": s - s.shift(120),
        "相对偏离年线": s - s.rolling(250, min_periods=200).mean(),
    }
    if g in ia and v in ia and ia[g].notna().sum() > 500 and ia[v].notna().sum() > 500:
        sig["成交额比z值"] = R.rolling_zscore(np.log(ia[g] / ia[v]), 250)
    if primary:
        grp = P.cfg["style"].get("growth_group")
        members = P.data.valid_groups().get(grp)
        if members:
            share = P.data.group_amount(members) / P.data.total_amount
            c = P.cfg["common"]
            sig["成长拥挤度"] = R.rolling_percentile(share, c["pct_window"], c["pct_min_periods"])
    macro = P.data.macro
    if macro is not None and "cn10y" in macro:
        sig["国债10Y变化60日"] = (macro["cn10y"] - macro["cn10y"].shift(60)) * 100
        if "cn2y" in macro:
            sig["期限利差"] = macro["cn10y"] - macro["cn2y"]
    sig["市场动量60日"] = R.past_return(P.data.market_close, 60)
    rg, rv = ic[g].pct_change(fill_method=None), ic[v].pct_change(fill_method=None)
    sig["相对波动率"] = np.log(rg.rolling(20).std() / rv.rolling(20).std())
    return {k: x.reindex(P.data.dates) for k, x in sig.items()}


def run(P: Panels) -> StudyResult:
    c = P.cfg["style"]
    res = StudyResult("D", "风格切换", "成长→价值、价值→成长之前有没有可观察的领先信号？", meta=P.meta())
    res.definitions = [
        f"风格相对线：log(成长/价值)，默认 {P.data.name(c['growth'])}/{P.data.name(c['value'])}；附加：" +
        "、".join(f"{P.data.name(a)}/{P.data.name(b)}" for a, b in c.get("extra_pairs", [])),
        f"切换点：风格相对线 zigzag({c['swing']:.0%}) 的峰/谷，每段 ≥ {c['min_days']} 个交易日；峰=成长→价值，谷=价值→成长",
        "信号方向预注册：信号越高 → 越可能发生成长→价值（小盘/大盘同理：越可能小盘→大盘）；因此预测力检验里“IC<0”才是符合假设的方向",
        f"预警：信号的扩展窗口分位 ≥ {c['alarm_hi']:.0%} 预示成长→价值、≤ {c['alarm_lo']:.0%} 预示价值→成长；"
        f"{c['alarm_window']} 日内发生对应切换算命中；同一方向预警间隔 ≥ {c['alarm_window']} 日",
        "基准概率：随机一天之后 60 日内发生该方向切换的比例",
        *[f"信号「{k}」：{v}" for k, v in SIGNAL_DESC.items()],
    ]
    pairs = [(c["growth"], c["value"], True)] + [(a, b, False) for a, b in c.get("extra_pairs", [])]
    all_ic, all_alarm = [], []
    any_pair = False
    for g, v, primary in pairs:
        ratio = style_ratio(P, g, v)
        a_name, b_name = (("成长", "价值") if primary else (P.data.name(g), P.data.name(v)))
        name = f"{P.data.name(g)}/{P.data.name(v)}"
        if ratio is None:
            res.caveats.append(f"缺少 {name} 的指数数据，跳过。")
            continue
        any_pair = True
        piv = switch_points(ratio, c["swing"], c["min_days"], a_name, b_name)
        piv_s = piv[piv["confirmed"] & P.in_study(piv["date"])].reset_index(drop=True) if not piv.empty else piv
        sigs = build_signals(P, g, v, ratio, primary)
        ic_tbl = _ic_table(P, sigs, np.log(ratio), c["horizons"])
        ic_tbl.insert(0, "风格对", name)
        al_tbl = _alarm_table(P, sigs, piv_s, c, a_name, b_name)
        al_tbl.insert(0, "风格对", name)
        all_ic.append(ic_tbl)
        all_alarm.append(al_tbl)
        if not piv_s.empty:
            sw = piv_s[["date", "方向", "前一段风格收益", "前一段天数"]].rename(columns={"date": "切换日"})
            sw["确认日"] = [P.data.dates[int(p)] for p in piv_s["confirm_pos"]]
            res.add(f"{name}：历史切换点", sw, "确认日 = 风格相对线反向走满阈值、现实中最早能确认切换的日子。")
            prof = _profile(sigs, piv_s, P, a_name, b_name)
            if not prof.empty:
                res.add(f"{name}：切换前的信号分位画像（仅描述，有选择偏差）", prof,
                        "数值为信号扩展窗口分位的平均值；0.5 = 平常水平。价格类信号在峰前偏高是定义使然，不构成证据。",
                        pct_cols=[])
    if not any_pair:
        res.findings.append("没有可用的风格指数数据（index_daily.csv 中需要成长/价值指数），研究D无法运行。")
        return res

    ic_all = pd.concat(all_ic, ignore_index=True)
    ic_all["q值"] = stats.bh_adjust(ic_all["p值"].to_numpy())
    ic_all["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q, bool(cs), P.grade_rule)]
                     for n, q, cs in zip(ic_all["独立样本≈"], ic_all["q值"], ic_all["两段同向"])]
    al_all = pd.concat(all_alarm, ignore_index=True)
    if not al_all.empty:
        al_all["q值"] = stats.bh_adjust(al_all["p值"].to_numpy())
        al_all["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q, bool(cs), P.grade_rule)]
                         for n, q, cs in zip(al_all["预警次数"], al_all["q值"], al_all["两段同向"])]
    res.tables.insert(0, _tbl("信号预测力：IC 与 Newey-West t 值", ic_all,
                              "IC = 信号与未来 h 日 log(成长/价值) 变化的秩相关；IC<0 表示信号高时成长随后跑输（符合预注册方向）。"
                              "p 值 = max(循环平移检验 p, 按独立样本数 N/h 的 t 检验 p)：持续性强的信号 + 重叠收益会让单一检验偏乐观"
                              "（在随机游走上模拟，NW 和单独的平移检验误报率可达 10%~15%），两者都显著才算数；NW 仅供对照。"
                              "独立样本≈ 样本天数/h。"))
    res.tables.insert(1, _tbl("预警检验：极端分位之后 60 日内是否真的切换", al_all,
                              "提升倍数 = 精确率/基准概率；p 值为二项检验（精确率是否高于基准）；召回率 = 有多少次切换之前出现过预警。"))

    # ---- 结论 ----
    good_ic = ic_all[ic_all["证据"].str.startswith(("A", "B"))]
    good_al = al_all[al_all["证据"].str.startswith(("A", "B"))] if not al_all.empty else al_all
    if good_ic.empty and good_al.empty:
        res.findings.append("所有候选信号在 FDR 校正后都没有达到 B 级以上——在这段样本里**没有找到可靠的风格切换领先信号**；"
                            "“看到X就切风格”的说法未被数据支持。")
    for _, r in good_ic.iterrows():
        lead = r["风格对"].split("/")[0] if not r["风格对"].startswith(P.data.name(c["growth"])) else "成长"
        direction = (f"符合预注册方向（信号高→{lead}随后跑输，均值回归）" if r["IC"] < 0
                     else f"与预注册方向相反（信号高→{lead}随后继续跑赢，是动量而非反转）")
        res.findings.append(f"[{r['风格对']}] {r['信号']} 对未来 {r['期限']} 日风格收益 IC={r['IC']:.3f}（p={r['p值']:.3f}，"
                            f"前段 {r['前段IC']:.3f}/后段 {r['后段IC']:.3f}，{r['证据']}），{direction}。")
    for _, r in good_al.iterrows():
        res.findings.append(f"[{r['风格对']}] {r['信号']} {r['预警']}：精确率 {pct(r['精确率'], 0)} vs 基准 {pct(r['基准概率'], 0)}"
                            f"（{r['预警次数']} 次预警，召回 {pct(r['召回率'], 0)}，{r['证据']}）。")
    if not al_all.empty:
        best = al_all.sort_values("提升倍数", ascending=False).head(3)
        res.findings.append("预警提升倍数最高的三项（不论显著与否）：" + "；".join(
            f"{r['风格对']}·{r['信号']}·{r['预警']} {r['提升倍数']:.2f}倍（n={r['预警次数']}）" for _, r in best.iterrows()) + "。")
    res.caveats += [
        "风格切换点一年只有一两次，十年大约 10~20 个——任何“信号”都很容易在这么少的样本上过拟合，所以只看 FDR 校正后的结果。",
        "价格类信号（相对动量、偏离年线）与切换点的定义高度相关，只有“预测力”和“预警”检验是干净的。",
        "宏观数据（国债收益率）为日度、无发布滞后；若加入 PMI、社融等月度数据，必须按公布日期对齐，否则是前视偏差。",
        "国证成长/价值的成分和编制方法与“茅指数/宁组合”等市场口径不同，结论依赖指数选择。",
    ]
    return res


def _tbl(title, df, note):
    from ..report import Table
    return Table(title, df, note)


def _ic_table(P: Panels, sigs: dict, s: pd.Series, horizons) -> pd.DataFrame:
    rows = []
    m_study = pd.Series(P.in_study(s.index), index=s.index)
    first = s.index <= P.split
    for name, x in sigs.items():
        for h in horizons:
            fwd = s.shift(-h) - s
            xs, fs = x[m_study], fwd[m_study]
            cs = stats.ic_test(xs, fs, h, n_perm=1000, rng=P.rng)
            ic = cs["ic"]
            z = (xs - xs.mean()) / xs.std()
            nw = stats.newey_west(fs.to_numpy(), z.to_numpy(), lags=h)
            ic1 = stats.spearman_ic(x[m_study & first], fwd[m_study & first])
            ic2 = stats.spearman_ic(x[m_study & ~first], fwd[m_study & ~first])
            n_days = int(pd.concat([xs, fs], axis=1).dropna().shape[0])
            rows.append({"信号": name, "期限": h, "IC": ic, "p值": cs["p"], "平移p": cs["p_shift"], "有效样本p": cs["p_neff"],
                         "NW t值": nw["t"], "NW p值": nw["p"],
                         "前段IC": ic1, "后段IC": ic2,
                         "两段同向": bool(np.isfinite(ic1) and np.isfinite(ic2) and ic1 * ic2 > 0),
                         "样本天数": n_days, "独立样本≈": n_days // h})
    return pd.DataFrame(rows)


def _alarm_table(P: Panels, sigs: dict, piv: pd.DataFrame, c: dict, a: str, b: str) -> pd.DataFrame:
    dates = P.data.dates
    n = len(dates)
    W = int(c["alarm_window"])
    study = P.in_study(dates)
    rows = []
    for direction, kind, level, hi in ((f"{a}→{b}", "peak", c["alarm_hi"], True), (f"{b}→{a}", "trough", c["alarm_lo"], False)):
        sw_pos = piv.loc[piv["kind"] == kind, "pos"].to_numpy(dtype=int) if not piv.empty else np.array([], dtype=int)
        # 每一天之后 W 日内是否有该方向切换
        upcoming = np.zeros(n, dtype=bool)
        for p in sw_pos:
            upcoming[max(0, p - W):p] = True
        # 基准只在研究区间、且未来 W 日完整的日子上计算
        valid = study.copy()
        valid[n - W:] = False
        base = upcoming[valid].mean() if valid.any() else np.nan
        split_pos = int(dates.searchsorted(P.split, side="right"))
        base1 = upcoming[valid & (np.arange(n) < split_pos)].mean() if (valid & (np.arange(n) < split_pos)).any() else np.nan
        base2 = upcoming[valid & (np.arange(n) >= split_pos)].mean() if (valid & (np.arange(n) >= split_pos)).any() else np.nan
        for name, x in sigs.items():
            pctl = R.expanding_percentile(x, P.cfg["common"]["pct_min_periods"])
            series = pctl if hi else 1 - pctl
            thr = level if hi else 1 - level
            al = crossing_events(series, thr, rearm=thr - 0.1, min_gap=W)
            al_pos = np.array([dates.get_loc(d) for d in al], dtype=int)
            al_pos = al_pos[valid[al_pos]] if len(al_pos) else al_pos
            hits = np.array([upcoming[p] for p in al_pos], dtype=bool)
            k, m = int(hits.sum()), len(al_pos)
            first = al_pos < split_pos
            prec1 = hits[first].mean() if first.any() else np.nan
            prec2 = hits[~first].mean() if (~first).any() else np.nan
            recall_hits = [np.any((al_pos >= p - W) & (al_pos < p)) for p in sw_pos if study[p]]
            leads = [p - al_pos[(al_pos >= p - W) & (al_pos < p)].min() for p in sw_pos
                     if study[p] and np.any((al_pos >= p - W) & (al_pos < p))]
            rows.append({
                "信号": name, "预警": f"{'≥' if hi else '≤'}{level:.0%}分位→{direction}",
                "预警次数": m, "命中": k, "精确率": k / m if m else np.nan, "基准概率": base,
                "提升倍数": (k / m) / base if m and base else np.nan,
                "p值": stats.binom_p_greater(k, m, base) if m else np.nan,
                "召回率": float(np.mean(recall_hits)) if recall_hits else np.nan,
                "提前天数中位(日)": float(np.median(leads)) if leads else np.nan,
                "两段同向": bool(np.isfinite(prec1) and np.isfinite(prec2) and prec1 > base1 and prec2 > base2),
            })
    return pd.DataFrame(rows)


def _profile(sigs: dict, piv: pd.DataFrame, P: Panels, a: str, b: str) -> pd.DataFrame:
    offsets = [-60, -40, -20, -10, 0]
    rows = []
    for name, x in sigs.items():
        pctl = R.expanding_percentile(x, P.cfg["common"]["pct_min_periods"]).to_numpy()
        for kind, label in (("peak", f"{a}→{b}"), ("trough", f"{b}→{a}")):
            pos = piv.loc[piv["kind"] == kind, "pos"].to_numpy(dtype=int)
            if len(pos) == 0:
                continue
            row = {"信号": name, "切换方向": label, "切换次数": len(pos)}
            for o in offsets:
                idx = pos + o
                idx = idx[(idx >= 0) & (idx < len(pctl))]
                row[f"T{o:+d}"] = float(np.nanmean(pctl[idx])) if len(idx) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)
