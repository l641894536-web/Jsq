"""研究E｜补涨扩散：龙头→二线→垃圾股扩散，是否真的意味着行情进入后段？

两个层面：
1. 行业内（需要个股数据）：
   - 每 20 个交易日，用当时可得信息把行业成分分成三层：
     龙头/中军 = 行业内流通市值前 20% 且最近财报盈利；二线 = 40%~80% 且盈利；尾部 = 市值后 40% 或亏损。
   - 在研究A识别出的每轮主线里，把谷底→相对顶部等分为早/中/后三段，比较三层的收益。
     H-E1：尾部相对龙头的超额在“后段”显著高于“早段”（配对 Wilcoxon 检验）；
     H-E2：早段龙头跑赢尾部（符号检验）。
   - 实时信号：强势行业里“尾部−龙头 10 日收益差”处于自身历史 90% 分位以上
     → 之后 40 日内见主线顶部的概率 是否高于强势行业的平常水平？未来超额是否更差？
2. 全市场：
   - 指数代理（无需个股）：国证2000/沪深300 的 20 日相对强度极端高 → 40 日内市场见顶概率？
   - 个股口径（有个股时）：亏损或市值后 20% 的“垃圾股”等权 vs 市值前 30% 盈利股。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

from ..core import returns as R
from ..core import stats
from ..core.events import condition_events, crossing_events, events_frame, restrict_dates
from ..core.eventstudy import add_grades, event_study
from ..core.zigzag import zigzag
from ..report import StudyResult, pct
from .a_lifecycle import detect_episodes
from .common import Panels

TIERS = ["龙头", "二线", "尾部"]


# ---------------------------------------------------------------- 个股面板
class StockPanel:
    def __init__(self, P: Panels):
        st = P.data.stocks
        dates = P.data.dates
        st = st.drop_duplicates(["date", "code"], keep="last").set_index(["date", "code"])
        self.close = st["close"].unstack().reindex(dates).astype("float32")
        self.close.columns = self.close.columns.astype(str)
        amount = st["amount"].unstack().reindex(dates).astype("float32")
        amount.columns = amount.columns.astype(str)
        amount = amount.reindex(columns=self.close.columns)
        # 分层来源：优先用数据自带的按时点分层（如中证指数成分），否则用 成交额/换手率 估算流通市值
        self.tier_given = None
        if "tier" in st.columns:
            t = st["tier"].astype(str).unstack().reindex(dates)
            t.columns = t.columns.astype(str)
            self.tier_given = t.reindex(columns=self.close.columns)
        turnover = (st["turnover"].unstack().reindex(dates).astype("float32") if "turnover" in st.columns
                    else pd.DataFrame(np.nan, index=dates, columns=self.close.columns, dtype="float32"))
        turnover.columns = turnover.columns.astype(str)
        turnover = turnover.reindex(columns=self.close.columns)
        ret = self.close.pct_change(fill_method=None)
        # 新股上市前 5 个交易日（常无涨跌幅限制）和明显的数据错误不参与
        age = self.close.notna().cumsum()
        ret = ret.where(age > 5).clip(-0.3, 0.3)
        self.ret = ret
        self.age = age
        mcap = amount / (turnover / 100.0)
        mcap = mcap.where(np.isfinite(mcap) & (mcap > 0))
        self.mcap = mcap.rolling(20, min_periods=5).median()
        self.dates = dates
        self.ind = P.data.stock_industry
        self.prof = P.data.stock_profit

    def sector_asof(self, d: pd.Timestamp) -> pd.Series:
        if self.ind is None:
            return pd.Series(dtype=object)
        x = self.ind[self.ind["start_date"] <= d].sort_values("start_date")
        return x.groupby("code")["sector"].last()

    def loss_asof(self, d: pd.Timestamp) -> pd.Series:
        if self.prof is None:
            return pd.Series(dtype=bool)
        x = self.prof[self.prof["ann_date"] <= d].sort_values(["report_date", "ann_date"])
        last = x.groupby("code")["net_profit"].last()
        return last < 0

    def tier_returns(self, reform_days: int, leader_pct: float, second_pct: float) -> dict[str, pd.DataFrame]:
        """返回 {层级: 日期×行业 的等权日收益}；分层只用调仓日及以前的信息，收益从下一交易日开始计。"""
        dates = self.dates
        out = {t: [] for t in TIERS}
        starts = list(range(260, len(dates), reform_days))
        for i, s in enumerate(starts):
            d = dates[s]
            e = starts[i + 1] if i + 1 < len(starts) else len(dates) - 1
            sector = self.sector_asof(d)
            if sector.empty:
                continue
            if self.tier_given is not None:
                tg = self.tier_given.iloc[s]
                ok = tg.notna() & (tg != "nan") & (self.age.iloc[s] >= 60)
                codes = tg.index[ok].intersection(sector.index)
                if len(codes) == 0:
                    continue
                df = pd.DataFrame({"sector": sector.reindex(codes), "tier": tg.reindex(codes)})
                loss = self.loss_asof(d).reindex(codes, fill_value=False).astype(bool)
                df.loc[loss.to_numpy(), "tier"] = "尾部"
            else:
                mc = self.mcap.iloc[s]
                ok = mc.notna() & (self.age.iloc[s] >= 60)
                codes = mc.index[ok].intersection(sector.index)
                if len(codes) == 0:
                    continue
                df = pd.DataFrame({"sector": sector.reindex(codes), "mcap": mc.reindex(codes)})
                loss = self.loss_asof(d).reindex(codes, fill_value=False).astype(bool)
                df["loss"] = loss
                df["pct"] = df.groupby("sector")["mcap"].rank(pct=True)
                df["tier"] = np.where((df["pct"] > leader_pct) & ~df["loss"], "龙头",
                                      np.where((df["pct"] > second_pct) & ~df["loss"], "二线", "尾部"))
            period = self.ret.iloc[s + 1:e + 1][codes]
            if period.empty:
                continue
            means = period.T.groupby([df["tier"].to_numpy(), df["sector"].to_numpy()]).mean().T  # 日期 × (tier, sector)
            for t in TIERS:
                if t in means.columns.get_level_values(0):
                    out[t].append(means[t])
        return {t: (pd.concat(v).sort_index().reindex(dates) if v else pd.DataFrame(index=dates)) for t, v in out.items()}

    def market_baskets(self, reform_days: int) -> tuple[pd.Series, pd.Series]:
        """全市场：垃圾股（亏损或市值后20%）与 优质大票（市值前30%且盈利）的等权日收益。"""
        dates = self.dates
        junk, quality = [], []
        starts = list(range(260, len(dates), reform_days))
        for i, s in enumerate(starts):
            d = dates[s]
            e = starts[i + 1] if i + 1 < len(starts) else len(dates) - 1
            if self.tier_given is not None:
                tg = self.tier_given.iloc[s]
                tg = tg[tg.notna() & (tg != "nan") & (self.age.iloc[s] >= 60)]
                if len(tg) < 50:
                    continue
                loss = self.loss_asof(d).reindex(tg.index, fill_value=False).astype(bool)
                j_codes = tg.index[(tg == "尾部") | loss]
                q_codes = tg.index[(tg == "龙头") & ~loss]
            else:
                mc = self.mcap.iloc[s]
                ok = mc.notna() & (self.age.iloc[s] >= 60)
                mc = mc[ok]
                if len(mc) < 50:
                    continue
                loss = self.loss_asof(d).reindex(mc.index, fill_value=False).astype(bool)
                p = mc.rank(pct=True)
                j_codes = mc.index[(p <= 0.2) | loss]
                q_codes = mc.index[(p > 0.7) & ~loss]
            period = self.ret.iloc[s + 1:e + 1]
            junk.append(period[j_codes].mean(axis=1))
            quality.append(period[q_codes].mean(axis=1))
        j = pd.concat(junk).reindex(dates) if junk else pd.Series(index=dates, dtype=float)
        q = pd.concat(quality).reindex(dates) if quality else pd.Series(index=dates, dtype=float)
        return j, q


# ---------------------------------------------------------------- 检验
def _alarm_vs_peaks(P: Panels, signal: pd.Series, peaks_pos: np.ndarray, level: float, window: int,
                    eligible: np.ndarray | None = None) -> dict:
    """信号分位 ≥ level 的预警，之后 window 日内是否出现顶部。"""
    dates = P.data.dates
    n = len(dates)
    pctl = R.expanding_percentile(signal, P.cfg["common"]["pct_min_periods"])
    al = crossing_events(pctl, level, rearm=level - 0.1, min_gap=window)
    upcoming = np.zeros(n, dtype=bool)
    for p in peaks_pos:
        upcoming[max(0, p - window):p] = True
    valid = P.in_study(dates).copy()
    valid[n - window:] = False
    if eligible is not None:
        valid &= eligible
    base = float(upcoming[valid].mean()) if valid.any() else np.nan
    al_pos = np.array([dates.get_loc(d) for d in al], dtype=int)
    al_pos = al_pos[valid[al_pos]] if len(al_pos) else al_pos
    hits = upcoming[al_pos] if len(al_pos) else np.array([], dtype=bool)
    split_pos = int(dates.searchsorted(P.split, side="right"))
    first = al_pos < split_pos
    idx = np.arange(n)
    b1 = upcoming[valid & (idx < split_pos)].mean() if (valid & (idx < split_pos)).any() else np.nan
    b2 = upcoming[valid & (idx >= split_pos)].mean() if (valid & (idx >= split_pos)).any() else np.nan
    p1 = hits[first].mean() if first.any() else np.nan
    p2 = hits[~first].mean() if (~first).any() else np.nan
    study_peaks = [p for p in peaks_pos if P.in_study(dates[[p]])[0]]
    recall = [np.any((al_pos >= p - window) & (al_pos < p)) for p in study_peaks]
    k, m = int(hits.sum()), len(al_pos)
    return {"预警次数": m, "命中": k, "精确率": k / m if m else np.nan, "基准概率": base,
            "提升倍数": (k / m) / base if m and base else np.nan,
            "p值": stats.binom_p_greater(k, m, base) if m else np.nan,
            "召回率": float(np.mean(recall)) if recall else np.nan, "顶部数": len(study_peaks),
            "两段同向": bool(np.isfinite(p1) and np.isfinite(p2) and p1 > b1 and p2 > b2),
            "_alarms": al_pos}


def _market_peaks(P: Panels) -> np.ndarray:
    piv = zigzag(P.data.market_close, P.cfg["diffusion"]["market_swing"])
    if piv.empty:
        return np.array([], dtype=int)
    return piv.loc[(piv["kind"] == "peak") & piv["confirmed"], "pos"].to_numpy(dtype=int)


def _market_test(P: Panels, rel_daily: pd.Series, label: str) -> tuple[dict, pd.DataFrame]:
    """rel_daily: 小票/垃圾股 相对 大票 的日超额；信号 = 20 日累计。"""
    c = P.cfg["diffusion"]
    sig = rel_daily.rolling(20, min_periods=15).sum()
    peaks = _market_peaks(P)
    a = _alarm_vs_peaks(P, sig, peaks, c["signal_pct"], c["alarm_window"])
    row = {"口径": label, **{k: v for k, v in a.items() if not k.startswith("_")}}
    # 预警后全市场收益 vs 随机日
    ev = pd.DataFrame({"date": P.data.dates[a["_alarms"]], "key": "全A"})
    mk = P.data.market_close.to_frame("全A")
    metrics = {f"全A未来{h}日收益": R.fwd_return(mk, h, P.lag) for h in (20, 60)}
    es = event_study(ev, metrics, None, P.split, P.cfg["common"]["n_perm"], P.cfg["common"]["n_boot"], P.rng,
                     period=P.period) if len(ev) else pd.DataFrame()
    if not es.empty:
        es.insert(0, "口径", label)
    return row, es


def run(P: Panels) -> StudyResult:
    c = P.cfg["diffusion"]
    res = StudyResult("E", "补涨扩散", "龙头→二线→垃圾股扩散，是否真的意味着行情进入后段？", meta=P.meta())
    tier_src = "tier" in P.data.stocks.columns if P.data.stocks is not None else False
    res.definitions = [
        ("分层（按时点）：数据自带的市值分层——龙头=沪深300成分，二线=中证500/中证1000成分，尾部=以外的小微盘/ST/次新"
         "（有财报时亏损股一律归尾部）；全市场“垃圾股”=尾部，“优质大票”=龙头" if tier_src else
         f"分层（每 {c['reform_days']} 个交易日重建，只用当时可得信息）：龙头=行业内流通市值前 {1 - c['leader_pct']:.0%} 且最近已公告财报盈利；"
        f"二线=市值 {c['second_pct']:.0%}~{c['leader_pct']:.0%} 分位且盈利；尾部=市值后 {c['second_pct']:.0%} 或亏损"),
        ("亏损 = 按公告日生效的最近一期财报净利润 < 0（无财报数据时不使用）" if tier_src else
         "流通市值估算 = 成交额 / 换手率（20 日中位数平滑）；亏损 = 按公告日生效的最近一期财报净利润 < 0"),
        "主线波段来自研究A；早/中/后段 = 谷底→相对顶部的时间三等分",
        f"扩散信号 = 尾部 − 龙头 的 {c['signal_window']} 日收益差，处于自身历史 {c['signal_pct']:.0%} 分位以上（仅在强势行业上）",
        f"市场顶部 = 中证全指 zigzag({c['market_swing']:.0%}) 的已确认峰；预警后 {c['alarm_window']} 日内见顶算命中",
        f"指数代理：{P.data.name(c['small_index'])}/{P.data.name(c['large_index'])} 的 20 日相对收益",
    ]

    # ---------- 全市场：指数代理 ----------
    mk_rows, mk_es = [], []
    ic = P.data.index_close
    if c["small_index"] in ic and c["large_index"] in ic:
        rel = ic[c["small_index"]].pct_change(fill_method=None) - ic[c["large_index"]].pct_change(fill_method=None)
        row, es = _market_test(P, rel, f"指数代理 {P.data.name(c['small_index'])}−{P.data.name(c['large_index'])}")
        mk_rows.append(row)
        mk_es.append(es)
    else:
        res.caveats.append("缺少小盘/大盘指数，跳过全市场指数代理检验。")

    has_stocks = P.data.stocks is not None and P.data.stock_industry is not None
    sp = None
    if has_stocks:
        sp = StockPanel(P)
        j, q = sp.market_baskets(c["reform_days"])
        row, es = _market_test(P, j - q, "个股口径 垃圾股−优质大票")
        mk_rows.append(row)
        mk_es.append(es)

    if mk_rows:
        mk = pd.DataFrame(mk_rows)
        mk["q值"] = stats.bh_adjust(mk["p值"].to_numpy())
        mk["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q_, bool(cs), P.grade_rule)]
                     for n, q_, cs in zip(mk["预警次数"], mk["q值"], mk["两段同向"])]
        res.add("全市场：小票/垃圾股极端跑赢之后，40 日内市场见顶的概率", mk,
                "基准概率 = 随机一天之后 40 日内出现市场顶部的比例；提升倍数 = 精确率/基准。")
        es_all = pd.concat([e for e in mk_es if not e.empty], ignore_index=True) if any(not e.empty for e in mk_es) else pd.DataFrame()
        if not es_all.empty:
            es_all = add_grades(es_all, P.grade_rule)
            res.add("全市场：预警之后全A收益 vs 随机日", es_all[["口径", "指标", "n", "独立簇", "均值", "胜率", "基准均值", "差值", "p值", "q值", "两段同向", "证据"]])
        for _, r in mk.iterrows():
            res.findings.append(
                f"{r['口径']}：极端跑赢预警 {int(r['预警次数'])} 次，其后 {c['alarm_window']} 日内市场见顶 {int(r['命中'])} 次"
                f"（精确率 {pct(r['精确率'], 0)} vs 基准 {pct(r['基准概率'], 0)}，召回 {pct(r['召回率'], 0)}，{r['证据']}）。"
            )

    if not has_stocks:
        res.findings.append("没有个股数据（stock_daily + stock_industry），行业内“龙头→二线→尾部”的扩散检验未运行。"
                            "运行 `python -m ashare_lab fetch --stocks` 获取后重跑。")
        res.caveats.append("指数代理（国证2000 vs 沪深300）只能反映“小票 vs 大票”，不等于“垃圾股”。")
        return res

    # ---------- 行业内：分层收益 ----------
    tiers = sp.tier_returns(c["reform_days"], c["leader_pct"], c["second_pct"])
    ep = detect_episodes(P)
    ep = ep[ep["_peak_ok"]] if not ep.empty else ep
    dates = P.data.dates
    ep_rows = []
    for _, e in ep.iterrows():
        code = e["代码"]
        if any(code not in tiers[t].columns for t in TIERS):
            continue
        t0, tp = int(e["_t0"]), int(e["_top"])
        tb = int(e["_bottom"]) if e["_bottom_ok"] else None
        if tp - t0 < 9:
            continue
        cuts = [t0, t0 + (tp - t0) // 3, t0 + 2 * (tp - t0) // 3, tp]
        row = {"行业": e["行业"], "谷底": e["谷底"], "相对顶部": e["相对顶部"]}
        valid = True
        for i, ph in enumerate(("早段", "中段", "后段")):
            for t in TIERS:
                r = tiers[t][code].iloc[cuts[i] + 1:cuts[i + 1] + 1]
                if r.notna().sum() < 0.6 * len(r):
                    valid = False
                row[f"{ph}{t}"] = float(np.prod(1 + r.fillna(0)) - 1)
        for i, ph in enumerate(("早段", "中段", "后段")):
            mkt_t = j.iloc[cuts[i] + 1:cuts[i + 1] + 1].fillna(0)
            mkt_l = q.iloc[cuts[i] + 1:cuts[i + 1] + 1].fillna(0)
            row[f"{ph}全市场尾部−龙头"] = float(np.prod(1 + mkt_t) - np.prod(1 + mkt_l))
        if tb is not None and tb > tp:
            for t in TIERS:
                r = tiers[t][code].iloc[tp + 1:tb + 1]
                row[f"顶部后{t}"] = float(np.prod(1 + r.fillna(0)) - 1)
        if valid:
            ep_rows.append(row)
    ep_tbl = pd.DataFrame(ep_rows)

    if not ep_tbl.empty:
        phase_rows = []
        for ph in ("早段", "中段", "后段", "顶部后"):
            if f"{ph}尾部" not in ep_tbl:
                continue
            sub = ep_tbl.dropna(subset=[f"{ph}尾部", f"{ph}龙头"])
            gap = sub[f"{ph}尾部"] - sub[f"{ph}龙头"]
            best = sub[[f"{ph}{t}" for t in TIERS]].idxmax(axis=1).str.replace(ph, "")
            phase_rows.append({
                "阶段": ph, "波段数": len(sub),
                **{f"{t}收益均值": sub[f"{ph}{t}"].mean() for t in TIERS},
                "尾部−龙头均值": gap.mean(), "尾部−龙头中位": gap.median(), "尾部跑赢龙头比例": (gap > 0).mean(),
                "尾部最强比例": (best == "尾部").mean(), "龙头最强比例": (best == "龙头").mean(),
            })
        phase = pd.DataFrame(phase_rows)
        res.add("主线各阶段的分层收益（逐波段等权平均）", phase)

        early = ep_tbl["早段尾部"] - ep_tbl["早段龙头"]
        late = ep_tbl["后段尾部"] - ep_tbl["后段龙头"]
        d = (late - early).dropna()
        tests = []
        if len(d) >= 5:
            w = sps.wilcoxon(d, alternative="greater")
            tests.append({"假设": "H-E1 后段(尾部−龙头) > 早段(尾部−龙头)", "n": len(d), "均值差": d.mean(),
                          "成立比例": (d > 0).mean(), "p值": float(w.pvalue)})
            k = int((early < 0).sum())
            tests.append({"假设": "H-E2 早段龙头跑赢尾部", "n": int(early.notna().sum()), "均值差": -early.mean(),
                          "成立比例": (early < 0).mean(), "p值": float(sps.binomtest(k, int(early.notna().sum()), 0.5, alternative="greater").pvalue)})
            gl = (late > 0)
            tests.append({"假设": "H-E3 后段尾部跑赢龙头", "n": int(late.notna().sum()), "均值差": late.mean(),
                          "成立比例": gl.mean(), "p值": float(sps.binomtest(int(gl.sum()), int(late.notna().sum()), 0.5, alternative="greater").pvalue)})
        tt = pd.DataFrame(tests)
        if not tt.empty:
            first = ep_tbl["谷底"] <= P.split
            cons = []
            for h in tt["假设"]:
                if h.startswith("H-E1"):
                    x = late - early
                elif h.startswith("H-E2"):
                    x = -early
                else:
                    x = late
                a, b = x[first].mean(), x[~first].mean()
                cons.append(bool(np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0))
            tt["两段同向"] = cons
            tt["q值"] = stats.bh_adjust(tt["p值"].to_numpy())
            tt["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q_, cs, P.grade_rule)] for n, q_, cs in zip(tt["n"], tt["q值"], tt["两段同向"])]
            res.add("扩散顺序的假设检验（跨主线波段）", tt, "H-E1 为配对 Wilcoxon 单侧检验；H-E2/H-E3 为符号检验。")
            for _, r in tt.iterrows():
                res.findings.append(f"{r['假设']}：{int(r['n'])} 轮主线中成立比例 {pct(r['成立比例'], 0)}，均值差 {pct(r['均值差'])}，"
                                    f"p={r['p值']:.3f}（{r['证据']}）。")
        # 探索性：剔除全市场大小盘风格后的行业内扩散
        adj_rows = []
        for ph in ("早段", "中段", "后段"):
            g = (ep_tbl[f"{ph}尾部"] - ep_tbl[f"{ph}龙头"]) - ep_tbl[f"{ph}全市场尾部−龙头"]
            adj_rows.append({"阶段": ph, "波段数": int(g.notna().sum()), "行业内尾部−龙头": (ep_tbl[f"{ph}尾部"] - ep_tbl[f"{ph}龙头"]).mean(),
                             "同期全市场尾部−龙头": ep_tbl[f"{ph}全市场尾部−龙头"].mean(), "剔除后均值": g.mean(),
                             "剔除后中位": g.median(), "剔除后为正比例": (g > 0).mean()})
        adj = pd.DataFrame(adj_rows)
        d_adj = ((ep_tbl["后段尾部"] - ep_tbl["后段龙头"] - ep_tbl["后段全市场尾部−龙头"])
                 - (ep_tbl["早段尾部"] - ep_tbl["早段龙头"] - ep_tbl["早段全市场尾部−龙头"])).dropna()
        if len(d_adj) >= 5:
            w_adj = sps.wilcoxon(d_adj, alternative="two-sided")
            adj_note = (f"探索性（非预注册）：剔除同期全市场“尾部−龙头”后，后段相对早段的扩散变化均值 {d_adj.mean() * 100:.1f}%，"
                        f"成立比例 {(d_adj > 0).mean():.0%}，双侧 Wilcoxon p={w_adj.pvalue:.3f}。")
        else:
            adj_note = "探索性：样本不足。"
        res.add("剔除全市场大小盘风格后的行业内扩散（探索性）", adj, adj_note)
        res.findings.append(adj_note)
        res.add("主线波段分层收益明细", ep_tbl, pct_cols=[c_ for c_ in ep_tbl.columns if c_ not in ("行业", "谷底", "相对顶部")])

    # ---------- 实时扩散信号 ----------
    tail, lead = tiers["尾部"], tiers["龙头"]
    common = [x for x in P.data.sector_close.columns if x in tail.columns and x in lead.columns]
    if common:
        W = int(c["signal_window"])
        diff = (tail[common].rolling(W, min_periods=W - 2).sum() - lead[common].rolling(W, min_periods=W - 2).sum())
        cc = P.cfg["common"]
        dpct = R.rolling_percentile_frame(diff, cc["pct_window"], cc["pct_min_periods"])
        cc_ = P.cfg["crash"]
        strong_now = ((P.rank60 <= cc_["strong_top_k"]) & (P.exc60 >= cc_["strong_min_exc60"]))[common]  # t 日收盘的强势状态
        cond = strong_now & (dpct >= c["signal_pct"])
        per = {k: condition_events(cond[k], int(c["alarm_window"])) for k in common}
        ev = restrict_dates(events_frame(per), P.study_start, P.study_end)
        if not ev.empty:
            metrics = {f"未来{h}日超额": P.fwd_exc(h)[common] for h in P.horizons}
            es = add_grades(event_study(ev, metrics, strong_now, P.split, cc["n_perm"], cc["n_boot"], P.rng, period=P.period), P.grade_rule)
            res.add("行业内扩散信号之后的未来超额（对照：强势但未扩散的日子）",
                    es[["指标", "n", "独立簇", "均值", "胜率", "基准均值", "差值", "均值90%CI低", "均值90%CI高", "p值", "q值", "两段同向", "证据"]])
            # 见顶概率
            tops = ep[["代码", "_top"]] if not ep.empty else pd.DataFrame(columns=["代码", "_top"])
            Wd = int(c["alarm_window"])
            n = len(dates)
            hits, base_num, base_den = [], 0, 0
            first_hits, second_hits, b1, b2 = [], [], [0, 0], [0, 0]
            split_pos = int(dates.searchsorted(P.split, side="right"))
            for k in common:
                up = np.zeros(n, dtype=bool)
                for tp in tops.loc[tops["代码"] == k, "_top"].astype(int):
                    up[max(0, tp - Wd):tp] = True
                el = strong_now[k].to_numpy() & P.in_study(dates)
                el[n - Wd:] = False
                base_num += int(up[el].sum())
                base_den += int(el.sum())
                idx = np.arange(n)
                b1[0] += int(up[el & (idx < split_pos)].sum()); b1[1] += int((el & (idx < split_pos)).sum())
                b2[0] += int(up[el & (idx >= split_pos)].sum()); b2[1] += int((el & (idx >= split_pos)).sum())
                for d_ in ev.loc[ev["key"] == k, "date"]:
                    p = dates.get_loc(d_)
                    if p < n - Wd:
                        hits.append(bool(up[p]))
                        (first_hits if p < split_pos else second_hits).append(bool(up[p]))
            base = base_num / base_den if base_den else np.nan
            kk, mm = int(np.sum(hits)), len(hits)
            cons = bool(first_hits and second_hits and b1[1] and b2[1]
                        and np.mean(first_hits) > b1[0] / b1[1] and np.mean(second_hits) > b2[0] / b2[1])
            pval = stats.binom_p_greater(kk, mm, base)
            top_tbl = pd.DataFrame([{"信号次数": mm, f"{Wd}日内见主线顶部": kk, "精确率": kk / mm if mm else np.nan,
                                     "强势行业基准概率": base, "提升倍数": (kk / mm) / base if mm and base else np.nan,
                                     "p值": pval, "两段同向": cons,
                                     "证据": stats.GRADE_TEXT[stats.evidence_grade(mm, pval, cons, P.grade_rule)]}])
            res.add("行业内扩散信号 → 主线见顶的概率", top_tbl, "基准 = 强势行业随机一天之后 40 日内见主线顶部的比例。")
            r = top_tbl.iloc[0]
            r20 = es[es["指标"] == "未来20日超额"]
            res.findings.append(
                f"行业内扩散信号（尾部−龙头 10 日收益差处于历史 90% 分位、且行业强势）共 {mm} 次："
                f"{Wd} 日内见主线顶部的比例 {pct(r['精确率'], 0)} vs 强势行业基准 {pct(r['强势行业基准概率'], 0)}（{r['证据']}）"
                + (f"；未来20日超额 {pct(r20.iloc[0]['均值'])} vs 基准 {pct(r20.iloc[0]['基准均值'])}（{r20.iloc[0]['证据']}）。" if not r20.empty else "。")
            )
    res.caveats += [
        "“垃圾股”没有统一定义：这里用“小市值或亏损”，没有用股价、ST、题材属性；ST 历史名单缺失会让部分 ST 股被归入其他层。",
        "个股列表若只取当前上市公司，会漏掉已退市股票（幸存者偏差）——这恰恰会低估垃圾股的真实跌幅。fetch 脚本会合并申万历史分类中的股票代码缓解这一问题。",
        "流通市值用 成交额/换手率 估算，是当日均价口径，与收盘市值略有差异，对分层影响很小。",
        "主线波段数量有限（一级行业约二三十轮），H-E1~H-E3 的检验力不高，“不显著”不等于“不存在”。",
    ]
    return res
