"""研究H｜拆解：把第一轮的稳健结论拆开看。

H1 主线按类型（成长/周期/消费/金融稳定）拆分研究A；
H2 成交占比创自身 99% 分位后的跑输，是“拥挤”还是“动量回落”？——与同一板块、过去 20 日超额同一五分位、
   但占比 <90% 分位的日子配对比较（预注册 H-B5）；
H3 研究C“次日确认”规律在不同条件下是否成立（跌幅档、行业自身/系统性、是否拥挤、市场环境、前后两段）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

from ..core import returns as R
from ..core import stats
from ..core.events import crossing_events, events_frame, restrict_dates
from ..report import StudyResult, pct
from .a_lifecycle import detect_episodes
from .b_crowding import unit_panels
from .c_crash import END, NEUTRAL, OPP, build_events
from .common import Panels

TYPES = {"type_growth": "成长", "type_cyclical": "周期", "type_consumer": "消费", "type_stable": "金融稳定"}


def sector_type(P: Panels, code: str) -> str:
    c = P.cfg["decompose"]
    look = P.data.sector_parent.get(code, code)
    for key, name in TYPES.items():
        if code in c[key] or look in c[key]:
            return name
    return "其他"


# ---------------------------------------------------------------- H1
def h1_by_type(P: Panels, res: StudyResult) -> None:
    ep = detect_episodes(P)
    if ep.empty:
        return
    ep = ep.copy()
    ep["类型"] = [sector_type(P, c) for c in ep["代码"]]
    rs = P.rs
    rows, groups_days, groups_bottom = [], {}, {}
    for t, sub in ep.groupby("类型"):
        ok = sub["_peak_ok"] & sub["_start"].notna()
        days = (sub.loc[ok, "_top"] - sub.loc[ok, "_start"]).astype(float)
        done = sub["_peak_ok"] & sub["_bottom_ok"]
        down = (sub.loc[done, "_bottom"] - sub.loc[done, "_top"]).astype(float)
        cr = sub[sub["_crowd"].notna() & sub["_peak_ok"]]
        rem = [rs[c].iloc[int(tp)] / rs[c].iloc[int(tc)] - 1 for c, tc, tp in zip(cr["代码"], cr["_crowd"], cr["_top"])]
        crb = cr[cr["_bottom_ok"]]
        hold = [rs[c].iloc[int(tb)] / rs[c].iloc[int(tc)] - 1 for c, tc, tb in zip(crb["代码"], crb["_crowd"], crb["_bottom"])]
        groups_days[t] = days.to_numpy()
        groups_bottom[t] = np.asarray(hold)
        rows.append({"类型": t, "主线数": len(sub), "谷→顶超额中位": sub["谷底→顶部超额"].median(),
                     "首次超额→顶部中位(日)": days.median() if len(days) else np.nan,
                     "顶部→底部中位(日)": down.median() if len(down) else np.nan,
                     "顶→底相对跌幅中位": sub.loc[done, "顶部→底部相对跌幅"].median(),
                     "拥挤后剩余超额中位": float(np.median(rem)) if rem else np.nan,
                     "拥挤后拿到底部超额中位": float(np.median(hold)) if hold else np.nan,
                     "拿到底部为负比例": float(np.mean(np.asarray(hold) < 0)) if hold else np.nan})
    tbl = pd.DataFrame(rows).sort_values("主线数", ascending=False)

    def kw(d):
        arrs = [v for v in d.values() if len(v) >= 3]
        return float(sps.kruskal(*arrs).pvalue) if len(arrs) >= 2 else np.nan

    p_days, p_hold = kw(groups_days), kw(groups_bottom)
    res.add("H1 主线按类型拆分", tbl, f"类型间差异（Kruskal-Wallis）：首次超额→顶部天数 p={p_days:.3f}；拥挤后拿到底部的超额 p={p_hold:.3f}。")
    if (tbl["类型"] == "其他").all():
        res.findings.append("H1：行业代码不在类型表中，无法按类型拆分。")
        return
    res.findings.append(
        "H1 主线类型：" + "；".join(f"{r['类型']} {int(r['主线数'])} 轮（首次超额→顶部中位 {r['首次超额→顶部中位(日)']:.0f} 日，"
                                  f"拥挤后剩余 {pct(r['拥挤后剩余超额中位'])}，拿到底部 {pct(r['拥挤后拿到底部超额中位'])}）"
                                  for _, r in tbl.iterrows() if r["类型"] != "其他")
        + f"。类型间时长差异 p={p_days:.3f}，“拿到底部”差异 p={p_hold:.3f}。"
    )


# ---------------------------------------------------------------- H2
def h2_matched(P: Panels, res: StudyResult) -> None:
    c = P.cfg["decompose"]
    cc = P.cfg["common"]
    closes, shares = unit_panels(P)
    for code in P.data.sector_close.columns:
        closes[P.data.name(code)] = P.data.sector_close[code]
        shares[P.data.name(code)] = P.share[code]
    closes = closes.loc[:, ~closes.columns.duplicated()]
    shares = shares.loc[:, ~shares.columns.duplicated()]
    spct = R.rolling_percentile_frame(shares, cc["pct_window"], cc["pct_min_periods"])
    exc20 = R.excess(R.past_return(closes, 20), R.past_return(P.data.market_close, 20))
    study = pd.Series(P.in_study(closes.index), index=closes.index)
    per = {u: crossing_events(spct[u], 0.99, rearm=0.89, min_gap=P.cfg["crowding"]["min_gap_days"]) for u in spct.columns}
    ev = restrict_dates(events_frame(per), P.study_start, P.study_end)
    if ev.empty:
        return
    rows = []
    for h in c["match_horizons"]:
        fwd = R.excess(R.fwd_return(closes, h, P.lag), R.fwd_return(P.data.market_close, h, P.lag))
        recs = []
        nq = c["match_quantiles"]
        cache = {}
        for d, u in zip(ev["date"], ev["key"]):
            if u not in cache:
                x = exc20[u][study]
                qs = x.quantile(np.linspace(0, 1, nq + 1)).to_numpy()
                bins = pd.Series(np.clip(np.searchsorted(qs, exc20[u].to_numpy(), side="right") - 1, 0, nq - 1), index=closes.index)
                ok = study & exc20[u].notna() & (spct[u] < c["match_max_pct"])
                f = fwd[u]
                pools = {k: f[ok & (bins == k)].dropna() for k in range(nq)}
                cache[u] = (bins, pools, f[study].dropna().mean())
            bins, pools, allmean = cache[u]
            v0, y0 = exc20.at[d, u], fwd.at[d, u]
            if not (np.isfinite(v0) and np.isfinite(y0)):
                continue
            k = int(bins.at[d])
            pool = pools[k]
            if len(pool) < 20:
                continue
            recs.append({"date": d, "key": u, "五分位": k + 1, "事件": y0, "配对基准": pool.mean(), "全体基准": allmean})
        r = pd.DataFrame(recs)
        if r.empty:
            continue
        r["配对差"] = r["事件"] - r["配对基准"]
        r["未配对差"] = r["事件"] - r["全体基准"]
        cl = stats.date_clusters(r["date"], 20, P.data.dates)
        x = r["配对差"].to_numpy()
        cb = stats.cluster_bootstrap(lambda ix: float(np.mean(x[ix])), cl, n_boot=cc["n_boot"], rng=P.rng)
        first = (r["date"] <= P.split).to_numpy()
        d1, d2 = x[first].mean() if first.any() else np.nan, x[~first].mean() if (~first).any() else np.nan
        cons = bool(np.isfinite(d1) and np.isfinite(d2) and d1 * d2 > 0)
        rows.append({"期限": h, "事件数": len(r), "独立簇": cb["clusters"], "未配对差": r["未配对差"].mean(),
                     "配对差": cb["stat"], "90%CI低": cb["lo"], "90%CI高": cb["hi"], "p值": cb["p"],
                     "前段差": d1, "后段差": d2, "两段同向": cons,
                     "事件落在最强五分位的比例": float((r["五分位"] == c["match_quantiles"]).mean())})
    t = pd.DataFrame(rows)
    if t.empty:
        return
    t["q值"] = stats.bh_adjust(t["p值"].to_numpy())
    t["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q, cs, P.grade_rule)] for n, q, cs in zip(t["独立簇"], t["q值"], t["两段同向"])]
    res.add("H2 占比创 99% 分位后的跑输：控制动量后还剩多少（H-B5）", t,
            "配对基准 = 同一板块、过去 20 日超额处于同一五分位、成交占比 <90% 分位的日子的未来超额均值；"
            "未配对差 = 与同一板块全部日子比（即第一轮的口径）。",
            pct_cols=["未配对差", "配对差", "90%CI低", "90%CI高", "前段差", "后段差", "事件落在最强五分位的比例"])
    for _, r in t.iterrows():
        res.findings.append(
            f"H2（H-B5）{int(r['期限'])} 日：与同板块全部日子相比差 {pct(r['未配对差'])}，控制过去 20 日动量后差 {pct(r['配对差'])}"
            f"（90%CI {pct(r['90%CI低'])}~{pct(r['90%CI高'])}，{r['证据']}）；{pct(r['事件落在最强五分位的比例'], 0)} 的事件本来就处于最强五分位。"
        )


# ---------------------------------------------------------------- H3
def h3_nextday(P: Panels, res: StudyResult) -> None:
    c = P.cfg["decompose"]
    cc = P.cfg["common"]
    ev = build_events(P)
    if ev.empty:
        return
    base = f"跌幅≥{min(P.cfg['crash']['drop_thresholds']):.0%}"
    e = ev[(ev["口径"] == base) & ev["结果"].isin([OPP, END, NEUTRAL]) & ev["次日涨跌"].notna()].reset_index(drop=True)
    if len(e) < 10:
        return
    from .f_regime import regime_labels
    lab = regime_labels(P)["均线法"].shift(1)
    e["环境"] = [lab.get(d, np.nan) for d in e["date"]]
    e["end"] = (e["结果"] == END).astype(float)
    e["down"] = e["次日涨跌"] < 0
    cl_all = stats.date_clusters(e["date"], 10, P.data.dates)
    end_a = e["end"].to_numpy(dtype=float)
    down_a = e["down"].to_numpy(dtype=bool)

    def gap(ix):
        dn = down_a[ix]
        if dn.sum() < 2 or (~dn).sum() < 2:
            return np.nan
        en = end_a[ix]
        return float(en[dn].mean() - en[~dn].mean())

    splits = {
        "跌幅档": np.where(e["当日跌幅"] <= -c["big_drop"], f"≥{c['big_drop']:.0%}", f"{min(P.cfg['crash']['drop_thresholds']):.0%}~{c['big_drop']:.0%}"),
        "行业自身/系统性": np.where(e["当日超额"] <= c["idio_cut"], "行业自身下跌", "系统性下跌"),
        "大跌前是否拥挤": np.where(e["成交占比分位"] >= c["crowd_cut"], "拥挤", "不拥挤"),
        "市场环境(均线法)": e["环境"].fillna("未知").to_numpy(),
        "时期": np.where(e["date"] <= P.split, "前段", "后段"),
    }
    rows, inter = [], []
    for sname, lab_arr in splits.items():
        lab_arr = np.asarray(lab_arr, dtype=object)
        levels = [lv for lv in pd.unique(lab_arr) if lv != "未知"]
        for lv in levels:
            ix = np.flatnonzero(lab_arr == lv)
            sub = e.iloc[ix]
            cb = stats.cluster_bootstrap(lambda j, ix=ix: gap(ix[j]), cl_all[ix], n_boot=cc["n_boot"], rng=P.rng)
            rows.append({"拆分": sname, "分组": lv, "事件数": len(ix), "独立簇": cb["clusters"],
                         "次日续跌→结束比例": sub.loc[sub["down"], "end"].mean(), "次日收涨→结束比例": sub.loc[~sub["down"], "end"].mean(),
                         "差值": cb["stat"], "90%CI低": cb["lo"], "90%CI高": cb["hi"], "p值": cb["p"]})
        if len(levels) == 2:
            a_ix, b_ix = np.flatnonzero(lab_arr == levels[0]), np.flatnonzero(lab_arr == levels[1])
            both = np.r_[a_ix, b_ix]
            is_a = np.r_[np.ones(len(a_ix), bool), np.zeros(len(b_ix), bool)]

            def diff(j, both=both, is_a=is_a):
                sel = both[j]
                ga = gap(sel[is_a[j]])
                gb = gap(sel[~is_a[j]])
                return ga - gb

            cb = stats.cluster_bootstrap(diff, cl_all[both], n_boot=cc["n_boot"], rng=P.rng)
            inter.append({"拆分": sname, "比较": f"{levels[0]} − {levels[1]}", "差值之差": cb["stat"],
                          "90%CI低": cb["lo"], "90%CI高": cb["hi"], "p值": cb["p"]})
    t = pd.DataFrame(rows)
    t["q值"] = stats.bh_adjust(t["p值"].to_numpy())
    it = pd.DataFrame(inter)
    if not it.empty:
        it["q值"] = stats.bh_adjust(it["p值"].to_numpy())
    pc = ["次日续跌→结束比例", "次日收涨→结束比例", "差值", "90%CI低", "90%CI高"]
    res.add("H3 次日确认规律的异质性（各分组内：次日续跌 − 次日收涨 的趋势结束比例差）", t,
            f"样本：{base} 的强势板块大跌；按日期簇自助法；q 值为全表 BH 校正（探索性）。", pct_cols=pc)
    if not it.empty:
        res.add("H3 组间差异（交互作用）", it, "差值之差 ≠ 0 表示该条件会改变次日确认的效果。",
                pct_cols=["差值之差", "90%CI低", "90%CI高"])
    held = t[(t["差值"] > 0) & (t["90%CI低"] > 0)]
    res.findings.append(
        f"H3 次日确认：在 {len(t)} 个分组中，差值为正且 90%CI 不含 0 的有 {len(held)} 个；差值为负的分组 {int((t['差值'] < 0).sum())} 个。"
        + ("最强的分组：" + "；".join(f"{r['拆分']}·{r['分组']} {pct(r['差值'], 0)}（n={int(r['事件数'])}）"
                                   for _, r in t.nlargest(3, "差值").iterrows()) if len(t) else "")
    )
    if not it.empty:
        sig = it[it["p值"] < 0.10]
        res.findings.append("H3 交互作用：" + ("；".join(f"{r['拆分']}（{r['比较']} = {pct(r['差值之差'], 0)}，p={r['p值']:.3f}，q={r['q值']:.3f}）"
                                                  for _, r in sig.iterrows()) if len(sig) else "没有任何条件在 p<0.10 水平上改变次日确认的效果——规律在各条件下大体一致。"))


def run(P: Panels) -> StudyResult:
    res = StudyResult("H", "拆解研究", "第一轮的稳健结论，拆开看是否依然成立、在什么条件下成立？", meta=P.meta())
    c = P.cfg["decompose"]
    res.definitions = [
        "H1 主线类型：成长（TMT/电新/军工/医药）、周期（煤炭/石化/有色/钢铁/化工/建材/机械/汽车）、"
        "消费（食饮/家电/美护/社服/纺服/商贸/轻工/农林）、金融稳定（银行/非银/地产/公用/交运/建筑/环保/综合）；细分行业按其所属申万一级归类",
        f"H2 配对基准：同一板块、过去 20 日超额处于同一{c['match_quantiles']}分位组、成交占比 <{c['match_max_pct']:.0%} 分位的日子",
        f"H3 分组：跌幅 ≥{c['big_drop']:.0%}；当日超额 ≤{c['idio_cut']:.0%} 为行业自身下跌；大跌前占比分位 ≥{c['crowd_cut']:.0%} 为拥挤；市场环境为研究F均线法",
    ]
    h1_by_type(P, res)
    h2_matched(P, res)
    h3_nextday(P, res)
    res.caveats = [
        "H1、H3 为探索性拆分（分组多、样本少），只看方向与置信区间，不据此单独立规律。",
        "H2 的五分位分界用研究区间内全部日子计算，是评估用的对照组，不是交易信号。",
    ]
    return res
