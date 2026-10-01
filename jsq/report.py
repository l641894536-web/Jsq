"""根据 results/<run>/ 下的 CSV 生成单文件 HTML 报告（无外部依赖，浏览器直接打开）。"""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import FEATURE_CN
from .config import EXIT_PROFILES, TRADFI_KEYWORDS

EXIT_CN = {"sig": "信号进出", "sl3": "3ATR止损", "sl3tp6": "3ATR止损+6ATR止盈", "trail4": "4ATR移动止损",
           "sl4_24h": "4ATR止损+最长24h", "sl4_72h": "4ATR止损+最长72h"}

DARK = "--bg:#0f1113;--fg:#e6e8ea;--mut:#9aa1a8;--card:#171a1d;--line:#262b30;--pos:74,222,128;--neg:248,113,113;--acc:#60a5fa;color-scheme:dark"
CSS = """
/* 单列报告：摘要 -> 分组一致性 -> 明细表；表格各自横向滚动 */
:root{--bg:#f7f8f9;--fg:#16191c;--mut:#6b737b;--card:#fff;--line:#e3e6e9;--pos:22,163,74;--neg:220,38,38;--acc:#2563eb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){%DARK%}}
:root[data-theme="dark"]{%DARK%}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1280px;margin:0 auto;padding-inline:16px;padding-block:24px 64px}h1{font-size:22px;margin:0 0 4px;text-wrap:balance}h2{font-size:17px;margin:36px 0 8px}
.mut{color:var(--mut)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.scroll{overflow-x:auto}table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;width:max-content;min-width:100%}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{position:sticky;top:0;background:var(--card);font-weight:600}
td.l,th.l{text-align:left}tr:hover td{background:rgba(127,127,127,.06)}.b{font-weight:700}
.tabs button{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 10px;border-radius:6px;margin:0 4px 6px 0;cursor:pointer;font:inherit}
.tabs button:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.tabs button.on{border-color:var(--acc);color:var(--acc)}.pane{display:none}.pane.on{display:block}
ul{padding-left:20px}li{margin:3px 0}code{background:rgba(127,127,127,.12);padding:1px 4px;border-radius:4px}
svg.sp{display:block}
""".replace("%DARK%", DARK)

JS = """
document.querySelectorAll('.tabs').forEach(t=>{const g=t.dataset.g;t.querySelectorAll('button').forEach(b=>b.onclick=()=>{
t.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
document.querySelectorAll('.pane[data-g="'+g+'"]').forEach(p=>p.classList.toggle('on',p.dataset.k===b.dataset.k));});});
"""


def _e(x) -> str:
    return html.escape(str(x))


def pct(x, d=1) -> str:
    return "–" if x is None or not np.isfinite(x) else f"{x * 100:.{d}f}%"


def num(x, d=2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    if isinstance(x, float) and np.isinf(x):
        return "∞"
    return f"{x:.{d}f}"


def _bg(v, scale) -> str:
    if v is None or not np.isfinite(v) or scale <= 0:
        return ""
    a = min(abs(v) / scale, 1.0) * 0.55
    rgb = "var(--pos)" if v > 0 else "var(--neg)"
    return f' style="background:rgba({rgb},{a:.2f})"'


def _table(head: list[str], rows: list[list[str]], left_cols: int = 1) -> str:
    th = "".join(f'<th class="{"l" if i < left_cols else ""}">{h}</th>' for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(rows_i) + "</tr>" for rows_i in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _tabs(group: str, panes: dict[str, str]) -> str:
    keys = list(panes)
    btn = "".join(f'<button data-k="{_e(k)}" class="{"on" if i == 0 else ""}">{_e(k)}</button>'
                  for i, k in enumerate(keys))
    body = "".join(f'<div class="pane {"on" if i == 0 else ""}" data-g="{group}" data-k="{_e(k)}">{v}</div>'
                   for i, (k, v) in enumerate(panes.items()))
    return f'<div class="tabs" data-g="{group}">{btn}</div>{body}'


def _spark(curve: pd.Series | None, bench: pd.Series | None, w=170, h=38) -> str:
    if curve is None or len(curve) < 2:
        return ""
    def pts(s):
        s = s.iloc[np.linspace(0, len(s) - 1, min(len(s), 140)).astype(int)]
        return s.to_numpy()
    a = pts(curve)
    b = pts(bench) if bench is not None and len(bench) > 1 else None
    allv = np.concatenate([a, b]) if b is not None else a
    lo, hi = float(np.nanmin(allv)), float(np.nanmax(allv))
    rng = hi - lo or 1.0
    def poly(v):
        xs = np.linspace(1, w - 1, len(v))
        ys = h - 2 - (v - lo) / rng * (h - 4)
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    y1 = h - 2 - (1 - lo) / rng * (h - 4)
    out = f'<svg class="sp" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
    out += f'<line x1="0" x2="{w}" y1="{y1:.1f}" y2="{y1:.1f}" stroke="currentColor" stroke-opacity=".15"/>'
    if b is not None:
        out += f'<polyline fill="none" stroke="currentColor" stroke-opacity=".35" stroke-dasharray="3 2" points="{poly(b)}"/>'
    color = "rgb(var(--pos))" if a[-1] >= 1 else "rgb(var(--neg))"
    out += f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{poly(a)}"/></svg>'
    return out


def asset_group(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    for cat, keys in TRADFI_KEYWORDS.items():
        if base in keys:
            return cat
    return "加密"


def build_report(run_dir: Path, top_n: int = 30, min_trades: int = 15, fragment: bool = False) -> Path:
    """fragment=True 时输出不带 <html>/<head> 外壳的版本（report_artifact.html），用于发布成 Artifact。"""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text()) if (run_dir / "meta.json").exists() else {}
    cov = pd.read_csv(run_dir / "coverage.csv")
    ic = pd.read_csv(run_dir / "ic.csv") if (run_dir / "ic.csv").exists() else pd.DataFrame()
    oos_p = run_dir / "oos_summary.csv"
    oos = pd.read_csv(oos_p) if oos_p.exists() else pd.DataFrame()
    curves = pd.read_csv(run_dir / "oos_curves.csv.gz", parse_dates=["time"]) \
        if (run_dir / "oos_curves.csv.gz").exists() else pd.DataFrame()
    best = json.loads((run_dir / "best_params.json").read_text()) if (run_dir / "best_params.json").exists() else {}
    symbols = list(cov["symbol"])

    parts = [f"<h1>币安合约 多空策略 / 因子有效性报告</h1>"
             f'<div class="mut">K线周期 {_e(meta.get("interval", ""))} · 手续费 {pct(meta.get("fee", 0), 3)}/边 · '
             f'滑点 {pct(meta.get("slippage", 0), 3)}/边 · {meta.get("folds", "")} 段滚动样本外 · '
             f'资金费按真实历史结算计入</div>']

    # 样本外天数
    oos_days = {}
    if "oos_start" in cov:
        for r in cov.itertuples():
            try:
                oos_days[r.symbol] = (pd.Timestamp(r.end) - pd.Timestamp(r.oos_start)).days + 1
            except (TypeError, ValueError):
                pass

    def _days(sym):
        d = oos_days.get(sym)
        if d is None:
            return ""
        return f"，样本外 {d} 天" + ("（⚠ 样本短，可能是运气）" if d < 180 else "")

    # ---------- 结论摘要
    summary = []
    if len(oos):
        cand = oos[(~oos["strategy"].isin(["buy_hold", "AUTO"])) & (oos["trades"] >= min_trades)]
        good = cand[(cand["sharpe"] > 0.5) & (cand["t_stat"] > 1.5) & (cand["folds_positive"] >= cand["folds"] / 2)]
        if len(good):
            g = good.sort_values("sharpe", ascending=False).head(8)
            items = "".join(
                f"<li><b>{_e(r.symbol)}</b> · {_e(r.label)}：样本外 {int(r.trades)} 笔，胜率 {pct(r.win_rate)}，"
                f"收益 {pct(r.total_return)}，夏普 {num(r.sharpe)}，最大回撤 {pct(r.max_drawdown)}，"
                f"{int(r.folds_positive)}/{int(r.folds)} 段盈利{_days(r.symbol)}</li>" for r in g.itertuples())
            summary.append(f"<p>样本外表现较稳健（夏普&gt;0.5、t&gt;1.5、至少一半时间段盈利、交易≥{min_trades}笔）的组合：</p><ul>{items}</ul>")
        else:
            summary.append("<p>没有任何“策略×标的”组合在样本外同时满足 夏普&gt;0.5、t&gt;1.5、半数以上时间段盈利。"
                           "这本身就是重要结论：这些规则在扣费后大概率没有稳定优势。</p>")
        auto = oos[oos["strategy"] == "AUTO"]
        if len(auto):
            items = "".join(f"<li>{_e(r.symbol)}：AUTO 样本外收益 {pct(r.total_return)}，夏普 {num(r.sharpe)}；"
                            f"买入持有 {pct(float(oos[(oos.symbol == r.symbol) & (oos.strategy == 'buy_hold')].total_return.iloc[0]))}</li>"
                            for r in auto.itertuples())
            summary.append("<p>AUTO = 每段只根据过去数据挑“当时最好的策略”。它比单个最优策略更接近实盘能拿到的结果：</p>"
                           f"<ul>{items}</ul>")
    if len(ic):
        st = ic[ic["stable"] & (ic["horizon_h"] >= 4)].copy()
        if len(st):
            st["abs_t"] = st["t"].abs()
            st = st.sort_values("abs_t", ascending=False).drop_duplicates(["symbol", "feature"]).head(10)
            items = "".join(
                f"<li><b>{_e(r.symbol)}</b> · {_e(r.feature_cn)} → 未来{int(r.horizon_h)}h：IC {num(r.ic, 3)} (t={num(r.t, 1)})，"
                f"{'值越高越容易涨' if r.ic > 0 else '值越高越容易跌'}；最高20%时上涨概率 {pct(r.q5_up_rate)}，"
                f"最低20%时 {pct(r.q1_up_rate)}</li>" for r in st.itertuples())
            summary.append(f"<p>前后半段方向一致且 |t|&gt;2 的预测因子：</p><ul>{items}</ul>")
        else:
            summary.append("<p>没有在前后两半样本中方向一致且显著(|t|&gt;2)的单因子。</p>")
    parts.append('<h2>结论摘要</h2><div class="card">' + "".join(summary) + "</div>")

    # ---------- 分组一致性：同类资产上是否普遍有效，比单个标的的好成绩可靠得多
    if len(oos):
        g = oos[oos["strategy"] != "buy_hold"].assign(grp=lambda x: x["symbol"].map(asset_group))
        groups = [c for c in ["加密", "贵金属", "能源", "美股/ETF"] if c in set(g["grp"])]
        labels = g.drop_duplicates("strategy").set_index("strategy")["label"]
        agg = g.groupby(["strategy", "grp"]).agg(sh=("sharpe", "mean"), pos=("total_return", lambda x: (x > 0).mean()),
                                                 n=("symbol", "nunique"))
        agg_all = g.groupby("strategy").agg(sh=("sharpe", "mean"), pos=("total_return", lambda x: (x > 0).mean()))
        rows = []
        for st in agg_all.sort_values("sh", ascending=False).index:
            r = [f'<td class="l">{_e(labels.get(st, st))} <span class="mut">{_e(st)}</span></td>']
            for gr in groups:
                if (st, gr) in agg.index:
                    a = agg.loc[(st, gr)]
                    r.append(f'<td{_bg(a.sh, 2)} title="{int(a.n)} 个标的">{num(a.sh)} · {pct(a.pos, 0)}</td>')
                else:
                    r.append("<td>–</td>")
            a = agg_all.loc[st]
            r.append(f"<td{_bg(a.sh, 2)}>{num(a.sh)} · {pct(a.pos, 0)}</td>")
            rows.append(r)
        ns = g.groupby("grp")["symbol"].nunique()
        parts.append('<h2>分组一致性（样本外）</h2><p class="mut">每格 = 该组所有标的的平均样本外夏普 · 盈利标的占比。'
                     '一个策略只在单个标的上好看很可能是运气；在同类多个标的上都赚钱才值得信。</p>'
                     + _table(["策略 \\ 资产组"] + [f"{_e(gr)}（{ns[gr]}）" for gr in groups] + ["全部"], rows))

    # ---------- 数据覆盖
    rows = [[f'<td class="l">{_e(r.symbol)}</td>', f"<td>{_e(r.start)}</td>", f"<td>{_e(r.end)}</td>",
             f"<td>{int(r.bars)}</td>", f"<td>{int(r.funding_settlements)}</td>",
             f"<td>{pct(r.funding_ann_mean)}</td>", f"<td>{'有' if r.has_premium else '无'}</td>",
             f"<td>{_e(getattr(r, 'oos_start', ''))}</td>",
             f"<td{_bg(r.buy_hold_return, 1)}>{pct(r.buy_hold_return)}</td>"] for r in cov.itertuples()]
    parts.append("<h2>数据覆盖</h2>" + _table(
        ["标的", "开始", "结束", "K线数", "资金费结算次数", "平均年化费率", "溢价数据", "样本外开始", "全期涨跌"], rows))

    # ---------- 预测力
    if len(ic):
        panes = {}
        feats = [f for f in FEATURE_CN if f in set(ic["feature"])]
        for hh in sorted(ic["horizon_h"].unique()):
            sub = ic[ic["horizon_h"] == hh]
            rows = []
            for f in feats:
                r = [f'<td class="l">{_e(FEATURE_CN.get(f, f))}</td>']
                for s in symbols:
                    x = sub[(sub["feature"] == f) & (sub["symbol"] == s)]
                    if not len(x):
                        r.append("<td>–</td>")
                        continue
                    x = x.iloc[0]
                    tip = (f"t={num(x.t, 1)} | 前半IC {num(x.ic_h1, 3)} 后半IC {num(x.ic_h2, 3)} | "
                           f"低20%均收益 {pct(x.q1_mean, 2)} 上涨率 {pct(x.q1_up_rate)} | "
                           f"高20%均收益 {pct(x.q5_mean, 2)} 上涨率 {pct(x.q5_up_rate)}")
                    cls = ' class="b"' if x.stable else ""
                    r.append(f'<td{_bg(x.ic, 0.08)} title="{_e(tip)}"><span{cls}>{num(x.ic, 3)}</span></td>')
                rows.append(r)
            panes[f"未来{hh}h"] = _table(["因子 \\ 标的"] + [_e(s) for s in symbols], rows)
        parts.append('<h2>因子预测力（Spearman IC）</h2><p class="mut">正值=因子越大未来越涨，负值=越大越跌。'
                     '加粗=前后半段方向一致且 |t|&gt;2。鼠标悬停看分组胜率。资金费率类若为负，说明“反向”有效。</p>'
                     + _tabs("ic", panes))

    # ---------- 策略 × 标的矩阵
    if len(oos):
        strat_rows = oos.drop_duplicates("strategy")[["strategy", "label"]].values.tolist()
        panes = {}
        for key, title, fmt, scale in (("sharpe", "夏普", lambda v: num(v), 2.0),
                                       ("win_rate", "胜率", lambda v: pct(v), None),
                                       ("total_return", "总收益", lambda v: pct(v), None),
                                       ("max_drawdown", "最大回撤", lambda v: pct(v), None),
                                       ("trades", "交易数", lambda v: num(v, 0), None),
                                       ("avg_hold_h", "平均持仓(h)", lambda v: num(v, 1), None)):
            rows = []
            for s, lab in strat_rows:
                r = [f'<td class="l">{_e(lab)} <span class="mut">{_e(s)}</span></td>']
                for sym in symbols:
                    x = oos[(oos["strategy"] == s) & (oos["symbol"] == sym)]
                    if not len(x):
                        r.append("<td>–</td>")
                        continue
                    v = float(x.iloc[0][key])
                    if key == "win_rate":
                        bg = _bg(v - 0.5, 0.15) if np.isfinite(v) else ""
                    elif key in ("total_return", "max_drawdown"):
                        bg = _bg(v, 0.5)
                    elif scale:
                        bg = _bg(v, scale)
                    else:
                        bg = ""
                    r.append(f"<td{bg}>{fmt(v)}</td>")
                rows.append(r)
            panes[title] = _table(["策略 \\ 标的"] + [_e(s) for s in symbols], rows)
        parts.append('<h2>策略 × 标的（样本外）</h2><p class="mut">每格是该策略在该标的上滚动样本外的结果，'
                     '参数和出场方式在每段开始前只用历史数据选出。</p>' + _tabs("mx", panes))

        # ---------- 排行
        cand = oos[~oos["strategy"].isin(["buy_hold"]) & (oos["trades"] >= min_trades)]
        cand = cand.sort_values("sharpe", ascending=False).head(top_n)
        cmap = {}
        if len(curves):
            for (s, st), g in curves.groupby(["symbol", "strategy"]):
                cmap[(s, st)] = g.set_index("time")["equity"]
        rows = []
        for r in cand.itertuples():
            rows.append([
                f'<td class="l"><b>{_e(r.symbol)}</b></td>', f'<td class="l">{_e(r.label)}</td>',
                f"<td>{int(r.trades)}</td>", f"<td{_bg(r.win_rate - 0.5, 0.15)}>{pct(r.win_rate)}</td>",
                f"<td>{pct(r.avg_trade, 2)}</td>", f"<td>{num(r.profit_factor)}</td>",
                f"<td{_bg(r.total_return, 0.5)}>{pct(r.total_return)}</td>", f"<td>{pct(r.max_drawdown)}</td>",
                f"<td{_bg(r.sharpe, 2)}>{num(r.sharpe)}</td>", f"<td>{num(r.t_stat, 1)}</td>",
                f"<td>{num(r.avg_hold_h, 1)}</td>",
                f"<td>{pct(r.long_win_rate)} / {pct(r.short_win_rate)}</td>",
                f"<td>{pct(r.funding_pnl, 2)}</td>",
                f"<td>{int(r.folds_positive)}/{int(r.folds)}</td>",
                f"<td>{_spark(cmap.get((r.symbol, r.strategy)), cmap.get((r.symbol, 'buy_hold')))}</td>"])
        parts.append(f'<h2>样本外排行 Top {len(cand)}</h2><p class="mut">按样本外夏普排序，至少 {min_trades} 笔交易。'
                     '曲线：实线=策略，虚线=买入持有。资金费损益为正表示净收到资金费。</p>' + _table(
                         ["标的", "策略", "交易数", "胜率", "平均每笔", "盈亏比", "总收益", "最大回撤", "夏普", "t值",
                          "平均持仓h", "多/空胜率", "资金费损益", "盈利段数", "样本外净值"], rows, left_cols=2))

    # ---------- 当前参数
    if best:
        rows = []
        for sym, d in best.items():
            for st, b in sorted(d.items(), key=lambda kv: -(kv[1].get("oos_sharpe") or -99)):
                rows.append([f'<td class="l">{_e(sym)}</td>', f'<td class="l">{_e(st)}</td>',
                             f'<td class="l">{_e(json.dumps(b["params"], ensure_ascii=False))}</td>',
                             f'<td class="l">{_e(EXIT_CN.get(b["exit"], b["exit"]))}</td>',
                             f"<td>{num(b['full_sharpe'])}</td>", f"<td{_bg(b['oos_sharpe'], 2)}>{num(b['oos_sharpe'])}</td>"])
        parts.append('<h2>实盘参数（用全部历史选出）</h2><p class="mut"><code>python -m jsq signal</code> 用这些参数计算当前多空信号。'
                     '全样本夏普偏乐观，请以样本外夏普为准。</p>'
                     + _table(["标的", "策略", "参数", "出场", "全样本夏普", "样本外夏普"], rows, left_cols=4))

    exits = "".join(f"<li><code>{_e(k)}</code> {_e(EXIT_CN.get(k, ''))}：{_e(v or '仅信号')}</li>"
                    for k, v in (meta.get("exit_profiles") or EXIT_PROFILES).items())
    parts.append(f"""<h2>方法与注意事项</h2><div class="card"><ul>
<li>信号在 K 线收盘计算，下一根开盘成交；每笔扣双边手续费+滑点；持仓跨过结算时刻按真实资金费率收付。</li>
<li>出场方式（也作为参数参与选优）：<ul>{exits}</ul>所有方式在信号反转/消失时也会离场，所以持仓时间不固定。</li>
<li>收益为 1 倍杠杆、全仓复利。加杠杆收益和回撤近似同比放大，且有爆仓风险。</li>
<li>测试的组合越多，越容易碰巧找到“好”结果。只看样本外，并优先选：交易数多、t 值高、多数时间段都盈利、在多个相似标的上都有效的策略。</li>
<li>币安 TradFi（黄金/白银/原油/美股）合约上线时间短，样本少，结论可信度明显低于 BTC。美股合约在美股休市时段（夜间、周末）价格行为与交易时段不同。</li>
<li>本报告是历史统计，不构成投资建议。</li></ul></div>""")

    title = "币安合约策略回测"
    if fragment:
        page = f'<title>{title}</title><style>{CSS}</style><main>{"".join(parts)}</main><script>{JS}</script>'
        out = run_dir / "report_artifact.html"
    else:
        page = (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head>'
                f'<body><main>{"".join(parts)}</main><script>{JS}</script></body></html>')
        out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out
