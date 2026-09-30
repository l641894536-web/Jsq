"""研究F｜市场环境：牛市、熊市、震荡市分别应该采用什么策略？

方法：
1. 环境划分（t 日只用 t 日及以前数据）：
   - 均线法：中证全指在年线之上且年线上行 = 牛；之下且下行 = 熊；其余 = 震荡；
   - 动量法：过去 120 日涨幅 > 15% = 牛；< −15% = 熊；其余 = 震荡；
   - 事后标签（未来 120 日涨跌，只作“完美识别”的上限对照，不可交易）。
2. 一组简单、透明的候选策略（全部 t 日收盘出信号、按 entry_lag 延迟成交、扣单边 10bp 成本）：
   行业动量、行业反转、指数均线择时、超跌买入、红利/防御、小盘、买入持有。
3. 按“持仓决策时已知的环境”拆分每个策略的表现。
4. 关键检验——“分环境用不同策略”是否真的更好：
   逐年滚动（只用过去数据）为每种环境挑夏普最高的策略，下一年按实时环境切换；
   对照：同样逐年滚动、但不分环境只挑一个最优策略；以及买入持有。
   两者日收益差用移动块自助法给置信区间。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import backtest as B
from ..core import regimes as G
from ..core import stats
from ..report import StudyResult, pct
from .common import Panels

HOLD = "买入持有全A"
CASH = "空仓"


def build_strategies(P: Panels) -> dict[str, pd.Series]:
    c = P.cfg["regime"]
    lag, cost = P.lag, c["cost_bps"]
    dates = P.data.dates
    sec_ret = P.ret
    mkt = P.data.market_close
    mret = P.mret.to_frame("全A")
    out = {}
    mom = P.data.sector_close / P.data.sector_close.shift(20) - 1
    w = B.hold_every(B.top_k_weights(mom, c["momentum_top"], largest=True), c["rebalance_days"])
    out["行业动量(前5)"] = B.run_weights(w, sec_ret, lag, cost)
    w = B.hold_every(B.top_k_weights(mom, c["reversal_bottom"], largest=False), c["rebalance_days"])
    out["行业反转(后5)"] = B.run_weights(w, sec_ret, lag, cost)
    ma20 = mkt.rolling(20).mean()
    out["均线择时(MA20)"] = B.run_weights((mkt > ma20).astype(float).to_frame("全A"), mret, lag, cost)
    r5 = mkt / mkt.shift(5) - 1
    trig = (r5 < c["dip_threshold"]).astype(float)
    hold = trig.rolling(c["dip_hold"], min_periods=1).max()
    out["超跌买入"] = B.run_weights(hold.to_frame("全A"), mret, lag, cost)
    ic = P.data.index_close
    div = c.get("dividend_index")
    if div in ic and ic[div].notna().sum() > 0.8 * len(dates):
        r = ic[div].pct_change(fill_method=None).to_frame("红利")
        out["红利"] = B.run_weights(pd.DataFrame({"红利": 1.0}, index=dates), r, lag, cost)
    else:
        members = P.data.valid_groups().get(c.get("defensive_group", ""), [])
        if members:
            w = pd.DataFrame(1.0 / len(members), index=dates, columns=members)
            out["防御组合"] = B.run_weights(w, sec_ret[members], lag, cost)
    sm = c.get("small_index")
    if sm in ic and ic[sm].notna().sum() > 0.8 * len(dates):
        r = ic[sm].pct_change(fill_method=None).to_frame("小盘")
        out["小盘指数"] = B.run_weights(pd.DataFrame({"小盘": 1.0}, index=dates), r, lag, cost)
    out[HOLD] = B.run_weights(pd.DataFrame({"全A": 1.0}, index=dates), mret, lag, cost)
    out[CASH] = pd.Series(0.0, index=dates)
    return out


def regime_labels(P: Panels) -> dict[str, pd.Series]:
    c = P.cfg["regime"]
    mkt = P.data.market_close
    n = int(c.get("min_persist", 1))
    return {
        "均线法": G.persist(G.regime_ma(mkt, c["ma_window"], c["ma_slope_window"]), n),
        "动量法": G.persist(G.regime_momentum(mkt, c["mom_window"], c["mom_up"], c["mom_down"]), n),
        "事后标签(不可交易)": G.persist(G.regime_oracle(mkt, c["oracle_window"], c["mom_up"], c["mom_down"]), n),
    }


def walk_forward(strats: pd.DataFrame, labels: pd.Series | None, years: list[int], min_days: int = 60,
                 cost_bps: float = 10.0) -> tuple[pd.Series, pd.DataFrame]:
    """逐年滚动选择：labels=None 时不分环境，只选一个历史夏普最高的策略。"""
    lab = labels.shift(1) if labels is not None else None  # 持仓决策时已知的环境
    out = pd.Series(np.nan, index=strats.index)
    picks = []
    for y in years:
        hist = strats[strats.index.year < y]
        cur = strats.index.year == y
        if labels is None:
            best = _pick(hist)
            out[cur] = strats.loc[cur, best].to_numpy()
            picks.append({"年份": y, "环境": "全部", "选中策略": best})
            continue
        lab_hist = lab[strats.index.year < y]
        choice = {}
        for g in G.LABELS:
            sub = hist[lab_hist == g]
            if len(sub) >= min_days:
                choice[g] = _pick(sub)
            else:
                choice[g] = HOLD
            picks.append({"年份": y, "环境": g, "选中策略": choice[g]})
        lab_cur = lab[cur]
        r = pd.Series(np.nan, index=strats.index[cur])
        for g, s in choice.items():
            m = (lab_cur == g).to_numpy()
            r[m] = strats.loc[cur, s][m]
        r[lab_cur.isna().to_numpy()] = strats.loc[cur, HOLD][lab_cur.isna().to_numpy()]
        # 切换策略的额外成本（近似：切换当天扣一次双边成本）
        sel = lab_cur.map(choice)
        switches = (sel != sel.shift()).to_numpy().copy()
        switches[0] = False
        r[switches] -= 2 * cost_bps / 1e4
        out[cur] = r.to_numpy()
    return out, pd.DataFrame(picks)


def _pick(hist: pd.DataFrame) -> str:
    """历史夏普最高的策略；如果所有策略夏普都为负，选空仓。"""
    sh = (hist.mean() / hist.std()).drop(CASH, errors="ignore")
    return CASH if sh.max() < 0 else str(sh.idxmax())


def run(P: Panels) -> StudyResult:
    c = P.cfg["regime"]
    res = StudyResult("F", "市场环境与策略", "牛市、熊市、震荡市分别应该采用什么策略？分环境切换策略是否真的比一套策略打天下更好？", meta=P.meta())
    res.definitions = [
        f"均线法：中证全指收盘在 {c['ma_window']} 日线上方且均线 {c['ma_slope_window']} 日斜率>0 = 牛市；下方且斜率<0 = 熊市；其余 = 震荡",
        f"动量法：过去 {c['mom_window']} 日涨幅 > {c['mom_up']:.0%} = 牛市；< {c['mom_down']:.0%} = 熊市；其余 = 震荡",
        f"事后标签：未来 {c['oracle_window']} 日涨跌（用了未来数据，仅作上限对照）",
        f"策略：行业动量=20日涨幅前{c['momentum_top']}行业等权、每{c['rebalance_days']}日调仓；行业反转=后{c['reversal_bottom']}；"
        f"均线择时=全A在20日线上持有否则空仓；超跌买入=全A 5日跌幅<{c['dip_threshold']:.0%}后持有{c['dip_hold']}日；"
        "红利=中证红利（缺失时用防御组合）；小盘=中证1000；买入持有=中证全指",
        f"成本：单边 {c['cost_bps']}bp；环境标签按“持仓前一日收盘已知”对齐；新环境需连续 {c.get('min_persist', 1)} 天才确认切换",
        "空仓也是候选：某环境下所有策略历史夏普都为负时，滚动选择会选空仓",
        "滚动检验：每年初只用过去数据，为每种环境选夏普最高的策略（该环境样本<60日则用买入持有）",
    ]
    strats = pd.DataFrame(build_strategies(P))
    study = P.in_study(strats.index)
    strats = strats[study]
    labels = {k: v.reindex(strats.index) for k, v in regime_labels(P).items()}

    # 1) 环境统计
    summ = []
    for k, lab in labels.items():
        s = G.regime_summary(lab)
        if not s.empty:
            s.insert(0, "划分方法", k)
            summ.append(s)
    res.add("环境划分：占比与持续时间", pd.concat(summ, ignore_index=True) if summ else pd.DataFrame())
    oracle = labels["事后标签(不可交易)"]
    agree_rows = []
    for k in ("均线法", "动量法"):
        both = pd.concat([labels[k], oracle], axis=1).dropna()
        agree_rows.append({"划分方法": k, "与事后标签一致比例": float((both.iloc[:, 0] == both.iloc[:, 1]).mean()) if len(both) else np.nan,
                           **{f"事后{g}时判为{g}的比例": float((both.iloc[:, 0][both.iloc[:, 1] == g] == g).mean()) if (both.iloc[:, 1] == g).any() else np.nan
                              for g in G.LABELS}})
    res.add("实时划分 vs 事后标签：识别准确度", pd.DataFrame(agree_rows),
            "这张表衡量“当时能不能认出现在是牛市/熊市”；比例低说明环境识别本身有显著滞后。")

    # 2) 分环境策略表现
    perf_rows = []
    for k, lab in labels.items():
        for name, r in strats.items():
            t = B.conditional_stats(r, lab)
            for _, row in t.iterrows():
                perf_rows.append({"划分方法": k, "环境": row["环境"], "策略": name, **row.drop("环境").to_dict()})
    perf = pd.DataFrame(perf_rows)
    for k in labels:
        sub = perf[perf["划分方法"] == k]
        if sub.empty:
            continue
        piv = sub.pivot_table(index="策略", columns="环境", values="夏普").reindex(columns=G.LABELS)
        ann = sub.pivot_table(index="策略", columns="环境", values="年化收益").reindex(columns=G.LABELS)
        tbl = pd.concat({"夏普": piv, "年化收益": ann}, axis=1)
        tbl.columns = [f"{a}·{b}" for a, b in tbl.columns]
        tbl = tbl.reset_index()
        res.add(f"分环境策略表现（{k}）", tbl, "按持仓前一日的环境标签拆分；年化收益按该环境内的交易日年化。",
                pct_cols=[c_ for c_ in tbl.columns if c_.startswith("年化收益")])
    full = pd.DataFrame([{"策略": n, **B.perf_stats(r)} for n, r in strats.items()])
    res.add("全样本策略表现（不分环境）", full)

    # 3) 分环境最优策略是否稳定（前后两段）
    stab_rows = []
    for k in ("均线法", "动量法"):
        lab = labels[k].shift(1)
        for g in G.LABELS:
            bests = []
            for half, m in (("前段", strats.index <= P.split), ("后段", strats.index > P.split)):
                sub = strats[m & (lab == g).to_numpy()]
                if len(sub) >= 60:
                    sh = sub.mean() / sub.std() * np.sqrt(B.TRADING_DAYS)
                    bests.append((half, sh.idxmax(), float(sh.max()), len(sub)))
                else:
                    bests.append((half, "样本不足", np.nan, len(sub)))
            stab_rows.append({"划分方法": k, "环境": g, "前段最优": bests[0][1], "前段夏普": bests[0][2], "前段天数": bests[0][3],
                              "后段最优": bests[1][1], "后段夏普": bests[1][2], "后段天数": bests[1][3],
                              "前后一致": bests[0][1] == bests[1][1] and bests[0][1] != "样本不足"})
    stab = pd.DataFrame(stab_rows)
    res.add("各环境最优策略在前后两段是否一致", stab)

    # 4) 滚动样本外检验
    years = sorted(set(strats.index.year))
    wf_years = [y for y in years if (strats.index.year < y).sum() >= 3 * B.TRADING_DAYS]
    wf_rows, picks_all = [], []
    if wf_years:
        m_oos = np.isin(strats.index.year, wf_years)
        static, picks = walk_forward(strats, None, wf_years, cost_bps=c["cost_bps"])
        picks_all.append(picks.assign(方法="不分环境"))
        series = {"滚动·不分环境单一最优": static[m_oos], "买入持有": strats[HOLD][m_oos]}
        for k in labels:
            ad, pk = walk_forward(strats, labels[k], wf_years, cost_bps=c["cost_bps"])
            series[f"滚动·分环境({k})"] = ad[m_oos]
            picks_all.append(pk.assign(方法=k))
        for name, r in series.items():
            wf_rows.append({"方案": name, **B.perf_stats(r)})
        wf = pd.DataFrame(wf_rows)
        # 显著性：分环境（实时）− 不分环境
        cmp_rows = []
        for k in ("均线法", "动量法", "事后标签(不可交易)"):
            d = (series[f"滚动·分环境({k})"] - series["滚动·不分环境单一最优"]).dropna()
            lo, hi = stats.block_bootstrap_mean_ci(d.to_numpy(), block=20, n_boot=P.cfg["common"]["n_boot"], rng=P.rng)
            yrs = d.groupby(d.index.year).mean()
            cmp_rows.append({"划分方法": k, "比较": f"分环境({k}) − 不分环境", "日均差(年化)": d.mean() * B.TRADING_DAYS,
                             "90%CI低(年化)": lo * B.TRADING_DAYS, "90%CI高(年化)": hi * B.TRADING_DAYS,
                             "跑赢年份比例": float((yrs > 0).mean()), "年数": len(yrs),
                             "显著": bool(np.isfinite(lo) and (lo > 0 or hi < 0))})
        cmp = pd.DataFrame(cmp_rows)
        res.add(f"滚动样本外检验（{wf_years[0]}—{wf_years[-1]}）", wf, "所有方案都只用当年之前的数据做选择。")
        res.add("分环境切换 vs 不分环境：差异的置信区间", cmp,
                "移动块自助法（20日块）；CI 不跨 0 才算显著。事后标签一行是“完美识别环境”的理论上限。",
                pct_cols=["日均差(年化)", "90%CI低(年化)", "90%CI高(年化)", "跑赢年份比例"])
        res.add("滚动选择记录", pd.concat(picks_all, ignore_index=True), max_rows=120)

        # ---- 结论 ----
        w = wf.set_index("方案")
        for _, r in cmp.iterrows():
            k = r["划分方法"]
            name = f"滚动·分环境({k})"
            sh_a, sh_s = w.loc[name, "夏普"], w.loc["滚动·不分环境单一最优", "夏普"]
            verdict = ("显著更好" if r["显著"] and r["日均差(年化)"] > 0 else
                       "显著更差" if r["显著"] else "差异不显著")
            res.findings.append(
                f"分环境切换策略（{k}）样本外夏普 {sh_a:.2f} vs 不分环境 {sh_s:.2f}，年化差 {pct(r['日均差(年化)'])}"
                f"（90%CI {pct(r['90%CI低(年化)'])}~{pct(r['90%CI高(年化)'])}，跑赢年份 {pct(r['跑赢年份比例'], 0)}）——{verdict}。"
            )
    for k in ("均线法", "动量法"):
        sub = perf[(perf["划分方法"] == k) & (perf["天数"] >= 60)]
        if sub.empty:
            continue
        parts = []
        for g in G.LABELS:
            s = sub[sub["环境"] == g]
            if s.empty:
                continue
            b = s.loc[s["夏普"].idxmax()]
            parts.append(f"{g}最优「{b['策略']}」(夏普 {b['夏普']:.2f}，年化 {pct(b['年化收益'])})")
        res.findings.append(f"全样本（{k}）：" + "；".join(parts) + "——这是样本内结论，要看下面的滚动检验才知道能否复制。")
    st = stab[stab["划分方法"] == "均线法"]
    if not st.empty:
        n_same = int(st["前后一致"].sum())
        res.findings.append(f"各环境的最优策略在前后两段一致的有 {n_same}/{len(st)} 个（均线法）"
                            + ("——环境与策略的对应关系不稳定，“牛市用X、熊市用Y”的经验需要谨慎。" if n_same < len(st) else "。"))
    ag = pd.DataFrame(agree_rows)
    if not ag.empty:
        res.findings.append("实时环境识别与事后标签的一致比例：" + "；".join(f"{r['划分方法']} {pct(r['与事后标签一致比例'], 0)}" for _, r in ag.iterrows())
                            + "——环境划分越滞后，分环境策略越难落地。")
    res.caveats = [
        "候选策略刻意保持简单（避免在策略设计上过拟合）；更复杂的策略请按同样的“滚动选择+样本外”框架加入 build_strategies。",
        "2015—2026 只有 2~3 轮完整的牛熊周期，“牛市/熊市”样本天数有限，分环境的夏普估计误差很大。",
        "指数层面回测忽略了涨跌停无法成交、ETF 跟踪误差和冲击成本；行业指数没有对应 ETF 的部分只能近似。",
        "环境划分参数（年线、±15%）已预注册；如需调整，必须同时报告原参数结果。",
    ]
    return res
