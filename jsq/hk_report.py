"""港股合约开盘研究报告：整理数据 -> 单文件 HTML（图表用内联 SVG + 原生 JS，含悬停提示与数据表视图）。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import excursion as xc
from . import hk
from . import hk_overnight as ho

FEE = 0.0005          # 单边手续费（taker）
CATS = {"over": "合约走过头", "under": "合约还没走够", "opposite": "合约方向相反"}
NAMES = {"ZHIPUUSDT": "智谱", "MINIMAXUSDT": "MiniMax", "HK1810USDT": "小米", "HK0700USDT": "腾讯(港币)",
         "TENCENTUSDT": "腾讯(美元)", "MEITUANUSDT": "美团", "POPMARTUSDT": "泡泡玛特", "BYDUSDT": "比亚迪",
         "KUAISHOUUSDT": "快手", "HK0625USDT": "HK0625", "HK0992USDT": "联想"}


def _r(x, n=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return round(float(x), n)


def minute_profile(P: dict, start="08:50", end="10:00") -> list[dict]:
    """各分钟（香港时间）合约与指数 1 分钟涨跌绝对值的平均（基点），所有标的所有交易日合并。"""
    acc: dict[str, list] = {}
    for p in P.values():
        cols = [c for c in p["close"].columns if start <= c <= end]
        for col_prev, col in zip(cols[:-1], cols[1:]):
            rp = np.log(p["close"][col] / p["close"][col_prev]).abs() * 1e4
            ri = np.log(p["index"][col] / p["index"][col_prev]).abs() * 1e4
            acc.setdefault(col, []).append((rp.dropna().to_numpy(), ri.dropna().to_numpy()))
    out = []
    for col in sorted(acc):
        rp = np.concatenate([a for a, _ in acc[col]])
        ri = np.concatenate([b for _, b in acc[col]])
        out.append({"t": col, "perp": _r(rp.mean(), 1), "index": _r(ri.mean(), 1)})
    return out


def categorize(T: pd.DataFrame) -> pd.Series:
    same = np.sign(T["perp_to_0929"]) == np.sign(T["gap"])
    over = same & (T["perp_to_0929"].abs() > T["gap"].abs())
    return pd.Series(np.where(~same, "opposite", np.where(over, "over", "under")), index=T.index)


def micro_costs(micro_dir: Path, symbols) -> pd.DataFrame:
    rows = []
    for s in symbols:
        p = Path(micro_dir) / f"{s}_micro.csv"
        if not p.exists():
            continue
        m = pd.read_csv(p)
        for w in ("open", "am_close"):
            x = m[m["window"] == w]
            rows.append({"symbol": s, "window": w, "days": len(x),
                         "spread_bps": x["spread_bps"].median(),
                         "notional_10min": x["notional"].median() if "notional" in x else np.nan,
                         "median_trade": x["median_trade"].median() if "median_trade" in x else np.nan,
                         "depth02": (x[["depth02_bid", "depth02_ask"]].mean(axis=1)).median()
                         if {"depth02_bid", "depth02_ask"} <= set(x.columns) else np.nan,
                         "depth1": (x[["depth1_bid", "depth1_ask"]].mean(axis=1)).median()
                         if {"depth1_bid", "depth1_ask"} <= set(x.columns) else np.nan})
    return pd.DataFrame(rows, columns=["symbol", "window", "days", "spread_bps", "notional_10min", "median_trade",
                                       "depth02", "depth1"])


def build_data(data_dir: Path, symbols=None, slippage: float = 0.0005) -> dict:
    d = Path(data_dir) / "hk1m"
    syms = [s for s in (symbols or hk.HK_SYMBOLS) if (d / f"{s}_1m_klines.csv").exists()]
    frames = {s: hk.load(s, d) for s in syms}
    T = pd.concat([hk.daily_table(f) for f in frames.values()], ignore_index=True)
    P = {s: hk.panel(f, start="08:50") for s, f in frames.items()}
    days = sorted({x for p in P.values() for x in p["close"].index})
    split = days[len(days) // 2]
    cost = FEE + slippage

    T = T.dropna(subset=["gap", "perp_to_0929"]).copy()
    T["cat"] = categorize(T)
    scatter = [{"s": NAMES.get(r.symbol, r.symbol), "d": r.day, "x": _r(r.gap * 100, 2),
                "y": _r(r.perp_to_0929 * 100, 2), "c": r.cat} for r in T.itertuples()]

    pre = hk.prepricing(T)
    pre_rows = [{"name": NAMES.get(r.symbol, r.symbol), "days": int(r.days), "gap": _r(r.abs_gap_bps, 0),
                 "p0859": _r(r.priced_0859 * 100, 0), "p0929": _r(r.priced_0929 * 100, 0),
                 "left": _r(r.left_0929_bps, 0), "same": _r(r.same_dir_0929 * 100, 0)} for r in pre.itertuples()]

    cats = []
    late = np.sign(T["gap"]) * T["after_11:59"] - 2 * cost
    early = np.sign(T["gap"]) * (T["post_11:59"] / T["p_0921"] - 1) - 2 * cost
    for k, label in CATS.items():
        m = T["cat"] == k
        cats.append({"key": k, "label": label, "share": _r(m.mean() * 100, 0), "n": int(m.sum()),
                     "late_bps": _r(late[m].mean() * 1e4, 0), "late_win": _r((late[m] > 0).mean() * 100, 0),
                     "early_bps": _r(early[m].mean() * 1e4, 0), "early_win": _r((early[m] > 0).mean() * 100, 0)})

    rob = hk.robustness(P, cost, split)
    base = pd.concat([hk.basis_trades(p, s, "09:31", "11:59", 0.003, 0.0) for s, p in P.items()], ignore_index=True)
    costs = micro_costs(Path(data_dir) / "hkmicro", syms)
    by_sym = []
    for s, g in base.groupby("symbol"):
        c_open = costs[(costs["symbol"] == s) & (costs["window"] == "open")]
        c_exit = costs[(costs["symbol"] == s) & (costs["window"] == "am_close")]
        spread_in = float(c_open["spread_bps"].iloc[0]) if len(c_open) and pd.notna(c_open["spread_bps"].iloc[0]) else np.nan
        spread_out = float(c_exit["spread_bps"].iloc[0]) if len(c_exit) and pd.notna(c_exit["spread_bps"].iloc[0]) else np.nan
        real_cost = 2 * FEE + ((spread_in if spread_in == spread_in else 10) + (spread_out if spread_out == spread_out else 10)) / 2 / 1e4
        net_assumed = g["gross"] - 2 * cost
        net_real = g["gross"] - real_cost
        by_sym.append({"symbol": s, "name": NAMES.get(s, s), "n": len(g),
                       "assumed": _r(net_assumed.mean() * 1e4, 0), "real": _r(net_real.mean() * 1e4, 0),
                       "real_cost": _r(real_cost * 1e4, 1), "win": _r((net_real > 0).mean() * 100, 0),
                       "mae90": _r(g["mae"].quantile(0.9) * 1e4, 0), "weak": s in hk.WEAK_SYMBOLS})
    by_sym.sort(key=lambda x: -(x["real"] if x["real"] is not None else -1e9))

    all_real = []
    for s, g in base.groupby("symbol"):
        rc = next((x["real_cost"] for x in by_sym if x["symbol"] == s), None)
        all_real.append(g["gross"] - (rc or 2 * cost * 1e4) / 1e4)
    all_real = pd.concat(all_real)
    net = base["gross"] - 2 * cost
    tiles = {"trades": len(base), "symbols": int(base["symbol"].nunique()),
             "exp_assumed": _r(net.mean() * 1e4, 0), "exp_real": _r(all_real.mean() * 1e4, 0),
             "t": _r(net.mean() / net.std(ddof=1) * np.sqrt(len(net)), 1), "win": _r((net > 0).mean() * 100, 0),
             "short_share": _r((base["side"] < 0).mean() * 100, 0)}

    grid = rob["grid"]
    grid_rows = [{"signal": r.signal, "exit": r.exit, "th": _r(r.threshold * 100, 1), "n": int(r.trades),
                  "exp": _r(r.exp_bps, 0), "t": _r(r.t, 1), "first": _r(r.exp_first_half, 0),
                  "second": _r(r.exp_second_half, 0), "t2": _r(r.t_second_half, 1)} for r in grid.itertuples()]
    stops = [{"stop": "不设" if r.stop == 0 else f"{r.stop:.0%}", "stopped": _r(r.stopped_share * 100, 0),
              "exp": _r(r.exp_bps, 0), "t": _r(r.t, 1), "win": _r(r.win_rate * 100, 0)} for r in rob["stops"].itertuples()]
    dec = rob["decomposition"].iloc[0]
    lunch = [{"exit": r.exit, "n": int(r.trades), "exp": _r(r.exp_bps, 0), "t": _r(r.t, 1)} for r in rob["lunch"].itertuples()]
    cost_rows = [{"name": NAMES.get(r.symbol, r.symbol), "window": "09:31-09:41" if r.window == "open" else "11:50-12:00",
                  "spread": _r(r.spread_bps, 1), "turnover": _r(r.notional_10min / 1e3, 0),
                  "trade": _r(r.median_trade, 0), "depth02": _r(r.depth02 / 1e3, 0), "depth1": _r(r.depth1 / 1e3, 0)}
                 for r in costs.itertuples()] if len(costs) else []
    # ---------- 收盘 → 次日开盘
    ref = hk.load("BABAUSDT", d) if (d / "BABAUSDT_1m_klines.csv").exists() else None
    O = pd.concat([ho.overnight_table(f, ref) for f in frames.values()], ignore_index=True)
    O = O[O["day_chg"].abs() <= 0.15].reset_index(drop=True)      # 去掉上市初期 ±15% 以上的极端日
    basis = O.merge(T[["symbol", "day", "basis_0931"]].rename(columns={"day": "next_day"}),
                    on=["symbol", "next_day"], how="left")["basis_0931"]
    basis.index = O.index
    ac = ho.after_close(O)
    after_rows = [{"bucket": r["bucket"], "n": int(r["n"]), "day": _r(r["day_chg_bps"] / 100, 1),
                   **{hm: [_r(r[f"{hm}_bps"], 0), _r((r[f"{hm}_up"] or 0) * 100, 0)] for hm in
                      ("18:00", "21:30", "04:00", "08:59", "09:29")}} for _, r in ac.iterrows()]
    fc = ho.four_cases(O)
    case_rows = [{"case": r["case"], "n": int(r["n"]), "day": _r(r["day_chg_bps"] / 100, 1),
                  "night": _r(r["overnight_bps"] / 100, 2), "gap": _r(r["gap_bps"] / 100, 2),
                  "open": _r(r["cont_open_bps"], 0), "open_t": _r(r["cont_open_t"], 1),
                  "am": _r(r["cont_am_bps"], 0), "am_t": _r(r["cont_am_t"], 1)} for _, r in fc.iterrows()]
    pr = ho.preopen_rules(O, basis, split)
    rule_rows = [{"rule": r.rule, "n": int(r.n), "exp": _r(r.exp_bps, 0), "win": _r(r.win * 100, 0), "t": _r(r.t, 1),
                  "first": _r(r.first_bps, 0), "second": _r(r.second_bps, 0), "sym": _r(r.sym_pos * 100, 0)}
                 for r in pr.itertuples()]
    dec_o = ho.decompose(O) if ref is not None else {}
    overnight = {"n": len(O), "after": after_rows, "cases": case_rows, "rules": rule_rows,
                 "paths": [{k: (_r(v, 0) if k != "t" else v) for k, v in p.items()} for p in ho.paths(O)],
                 "beta": _r(dec_o.get("beta", {}).get("slope"), 2), "mkt_t": _r(dec_o.get("market_vs_after", {}).get("t"), 1),
                 "own_t": _r(dec_o.get("own_vs_after", {}).get("t"), 1)}
    # ---------- 方向对不对 vs 能走多远（1R = 1%）、止损宽度
    gx = xc._hk_gather(P, O)
    touch = xc.hk_study(P, O, split, r_pct=0.01, gathered=gx)
    sgrid = xc.hk_stop_grid(P, O, split, gathered=gx)
    excursion = {
        "touch": [{"rule": r.rule, "exit": r.exit, "n": int(r.n), "t": _r(r.right_t, 1),
                   **{k: _r(getattr(r, k) * 100, 0) for k in ("right", "right_base", "wrong", "wrong_base", "none",
                                                              "two", "two_base")}} for r in touch.itertuples()],
        "stops": [{"rule": r.rule, "exit": r.exit, "stop": None if pd.isna(r.stop) else _r(r.stop * 100, 1),
                   "n": int(r.n), "exp": _r(r.exp_bps / 100, 2), "win": _r(r.win * 100, 0),
                   "first": _r(r.first_bps / 100, 2), "second": _r(r.second_bps / 100, 2),
                   "worst": _r(r.worst_bps / 100, 1), "adv90": _r(r.adv90_bps / 100, 1)} for r in sgrid.itertuples()],
    }
    # ---------- 拿到几点平 / 哪些合约有效 / 最近的信号
    etr = xc.hk_exit_trades(P, O)
    pc = lambda v: _r(v * 100, 2)
    excursion["curve"] = [{"rule": r.rule, "exit": r.exit, "n": int(r.n), "days": int(r.days), "exp": pc(r.exp),
                           "win": _r(r.win * 100, 0), "first": pc(r.first), "second": pc(r.second), "day_t": _r(r.day_t, 1)}
                          for r in xc.exit_curve(etr, split).itertuples()]
    bys = []
    for (rule, s), g in etr.groupby(["rule", "symbol"], sort=False):
        bys.append({"rule": rule, "name": NAMES.get(s, s), "n": len(g), "e1159": pc(g["11:59"].mean()),
                    "w1159": _r((g["11:59"] > 0).mean() * 100, 0), "e1330": pc(g["13:30"].mean()),
                    "second": pc(g.loc[g["day"] >= split, "11:59"].mean())})
    excursion["bysym"] = sorted(bys, key=lambda r: (r["rule"], -(r["e1159"] if r["e1159"] is not None else -99)))
    b2 = etr[etr["rule"] == xc.MAIN_RULES[1]]
    excursion["basis_sides"] = [{"side": "空" if sd < 0 else "多", "n": len(g), "exp": pc(g["11:59"].mean()),
                                 "first": pc(g.loc[g["day"] < split, "11:59"].mean()),
                                 "second": pc(g.loc[g["day"] >= split, "11:59"].mean())}
                                for sd, g in b2.groupby("side")]
    last = sorted(etr["day"].unique())[-10:]
    rec = etr[etr["day"].isin(last)].sort_values(["day", "rule", "symbol"], ascending=[False, True, True])
    excursion["recent"] = [{"day": r["day"], "name": NAMES.get(r["symbol"], r["symbol"]), "rule": r["rule"],
                            "side": "空" if r["side"] < 0 else "多", "move": pc(r["move"]),
                            "r1159": pc(r["11:59"]), "r1330": pc(r["13:30"])} for r in rec.to_dict("records")]

    return {
        "overnight": overnight, "excursion": excursion,
        "meta": {"symbols": len(syms), "obs": len(T), "start": min(T["day"]), "end": max(T["day"]),
                 "split": split, "cost_bps": _r(cost * 1e4, 0), "fee_bps": _r(FEE * 1e4, 0)},
        "profile": minute_profile(P), "scatter": scatter, "prepricing": pre_rows, "cats": cats,
        "tiles": tiles, "decomp": {"gross": _r(dec.gross_bps, 0), "stock": _r(dec.stock_part_bps, 0),
                                   "basis": _r(dec.basis_part_bps, 0), "mae_med": _r(dec.mae_median_bps, 0),
                                   "mae90": _r(dec.mae_p90_bps, 0)},
        "by_symbol": by_sym, "grid": grid_rows, "stops": stops, "lunch": lunch, "costs": cost_rows,
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_data(Path(sys.argv[1] if len(sys.argv) > 1 else "data")), ensure_ascii=False)[:2000])


PAGE = r"""<title>港股合约开盘研究</title>
<style>
/* 单列研究报告：结论 → 机制（分钟波动）→ 提前定价（散点）→ 追单陷阱 → 收敛策略（分标的柱图）→ 成本 → 用法 */
:root{
  --bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d68;--grid:#e1e0d9;--axis:#c3c2b7;
  --line:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--pos:#2a78d6;--neg:#e34948;
  --tint1:rgba(42,120,214,.10);--tint2:rgba(235,104,52,.12);--good:#006300;--bad:#b42323;
  --sans:system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a988f;--grid:#2c2c2a;--axis:#4a4a46;
  --line:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--pos:#3987e5;--neg:#e66767;
  --tint1:rgba(57,135,229,.16);--tint2:rgba(217,89,38,.18);--good:#0ca30c;--bad:#ff7b7b;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a988f;--grid:#2c2c2a;--axis:#4a4a46;
  --line:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--pos:#3987e5;--neg:#e66767;
  --tint1:rgba(57,135,229,.16);--tint2:rgba(217,89,38,.18);--good:#0ca30c;--bad:#ff7b7b;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 var(--sans)}
main{max-width:980px;margin:0 auto;padding-inline:16px;padding-block:28px 72px}
h1{font-size:26px;line-height:1.3;margin:0 0 6px;text-wrap:balance;letter-spacing:.01em}
h2{font-size:19px;margin:44px 0 6px;text-wrap:balance}
h3{font-size:15px;margin:22px 0 6px}
p{margin:8px 0;max-width:68ch}
.sub{color:var(--ink2);font-size:13.5px}
.mut{color:var(--muted)}
.lead{font-size:16px;max-width:70ch}
ul.key{padding-left:20px;margin:10px 0;max-width:72ch}ul.key li{margin:6px 0}
b.n{font-variant-numeric:normal}
.timeline{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:18px 0 6px}
.timeline div{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--surface)}
.timeline .t{font:600 13px/1.3 var(--mono);display:block}
.timeline .k{font-size:12.5px;color:var(--ink2)}
.timeline .auc{background:var(--tint2)}.timeline .trd{background:var(--tint1)}
figure{margin:16px 0;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 14px 10px;position:relative;min-width:0}
figcaption{font-size:13px;color:var(--ink2);margin-top:6px}
.fig-title{font-weight:600;font-size:14px;margin:0 0 2px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--ink2);margin:6px 0 4px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;width:14px;height:2px;border-radius:1px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%}
.chart{width:100%;min-width:0}
.chart svg{display:block;overflow:visible}
.chart svg:focus-visible{outline:2px solid var(--s1);outline-offset:2px;border-radius:4px}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:8px;
  box-shadow:0 4px 16px rgba(0,0,0,.12);padding:8px 10px;font-size:12.5px;line-height:1.45;min-width:150px;z-index:5}
.tip[hidden]{display:none!important}
.tip .h{color:var(--ink2);margin-bottom:4px}
.tip .r{display:flex;align-items:center;gap:8px;justify-content:space-between}
.tip .r .v{font-weight:650;color:var(--ink);font-variant-numeric:tabular-nums}
.tip .r .l{color:var(--ink2);display:inline-flex;align-items:center;gap:6px}
details.tv{margin-top:6px;font-size:13px}
details.tv summary{cursor:pointer;color:var(--ink2);width:max-content}
details.tv summary:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.scroll{overflow-x:auto;max-width:100%}
.scroll.tall{max-height:320px;overflow-y:auto}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;width:100%;min-width:max-content}
th,td{padding:6px 10px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
th{font-weight:600;color:var(--ink2);background:var(--surface);position:sticky;top:0}
td.l,th.l{text-align:left}
td.posv{color:var(--good)}td.negv{color:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile .lab{font-size:12.5px;color:var(--ink2)}
.tile .val{font-size:28px;font-weight:650;line-height:1.25;margin-top:2px}
.tile .note{font-size:12px;color:var(--muted)}
.callout{border-left:3px solid var(--s2);background:var(--surface);border-radius:0 8px 8px 0;padding:10px 14px;margin:14px 0;max-width:76ch}
code{font:13px/1.5 var(--mono);background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:1px 5px}
pre{font:13px/1.55 var(--mono);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px;overflow-x:auto}
@media (prefers-reduced-motion:no-preference){.tip{transition:opacity .08s}}
</style>
<main>
<h1>港股合约：收盘后怎么走，第二天开盘往哪回</h1>
<div class="sub" id="meta"></div>

<div class="timeline" aria-label="港交所交易时段（香港时间）">
  <div class="auc"><span class="t">09:00–09:20</span><span class="k">开市前竞价，09:15 后不可撤单</span></div>
  <div class="auc"><span class="t">09:20</span><span class="k">竞价撮合，开盘价确定</span></div>
  <div class="trd"><span class="t">09:30–12:00</span><span class="k">上午连续交易</span></div>
  <div><span class="t">12:00–13:00</span><span class="k">午休，只有合约在交易</span></div>
  <div class="trd"><span class="t">13:00–16:00</span><span class="k">下午连续交易</span></div>
  <div class="auc"><span class="t">16:00–16:10</span><span class="k">收市竞价；之后到次日开盘只有合约</span></div>
</div>

<h2>结论</h2>
<ul class="key" id="summary"></ul>

<h2>收盘后：合约往哪走</h2>
<p>按当天正股涨跌分组，看港股 16:10 收盘后合约相对收盘价的平均涨跌（基点）和上涨占比。</p>
<div class="scroll" id="t-after"></div>
<p class="mut" id="after-note"></p>

<h2>夜里涨了还是跌了：开盘时怎么回</h2>
<p>按 08:59（竞价前）合约相对收盘的涨跌分组，看两组的平均价格路径。</p>
<figure id="f-paths">
  <div class="fig-title">合约相对港股收盘价的平均走势（基点）</div>
  <div class="legend"><span><i class="sw" style="background:var(--s1)"></i>夜里涨 &gt;1%</span><span><i class="sw" style="background:var(--s2)"></i>夜里跌 &gt;1%</span></div>
  <div class="chart" id="c-paths"></div>
  <div class="tip" hidden></div>
  <details class="tv"><summary>数据表</summary><div class="scroll" id="t-paths"></div></details>
</figure>
<h3>白天涨跌 × 夜里涨跌：四种情况</h3>
<p class="mut">正数 = 顺着合约夜里的方向继续走（夜里跌的继续跌、夜里涨的继续涨），负数 = 往回走。白天涨跌超过 1%、夜里合约涨跌超过 0.5% 才归类。</p>
<div class="scroll" id="t-cases"></div>
<p id="beta-note"></p>

<h2>实盘规则（扣成本后）</h2>
<p>每笔按一来一回 0.2% 扣成本（实测约 0.11%–0.20%）。“前段 / 后段”以 <span id="split-day"></span> 为界分别统计。</p>
<div class="scroll" id="t-rules"></div>
<div class="callout"><b>怎么用：</b>每天 08:55 左右看合约相对昨天收盘涨了多少。涨超过 1% 就在 08:59 做空，拿到 11:59 到 13:30 之间平（13:30 平均多一点，波动也大一点）；止损不要设 1% 这种近的，最多设 3%。同一天好几个合约都出信号时，它们基本同涨同跌，仓位要分摊。夜里跌的不要抄底，也别在开盘前追空。</div>

<h2>止损和止盈怎么设：方向对不对 vs 能走多远</h2>
<p>把每次开仓之后的价格路径拆开看。1R = 止损距离，这里取开仓价的 1%。<b>方向对</b> = 先走到 +1R（还没碰到 −1R），<b>方向错</b> = 先碰到 −1R，<b>没走出来</b> = 到平仓时两边都没碰到。<b>对照</b> = 同一时刻随机猜方向，波动完全一样：价格本身来回晃，随便开一单也有不少能先走到 +1R，比对照高出来的部分才是判断力。</p>
<div class="scroll" id="t-touch"></div>
<p class="mut">t 为“方向对”比对照高出部分的显著性，大于 2 算显著。同一分钟里两边都碰到时按先亏算。</p>
<h3>止损设多宽：不设止盈，到点平仓</h3>
<div class="scroll" id="t-stopgrid"></div>
<div class="callout" id="stop-note"></div>

<h3>拿到几点平</h3>
<p>同一批单子换不同的平仓时间（不设止损）。“按天算的 t”把同一天的几笔合成一笔再算：同一天几个合约往往同涨同跌，等于只押了一注，大于 2 才算显著。</p>
<div class="scroll" id="t-curve"></div>
<h3>哪些合约有效</h3>
<div class="scroll" id="t-bysym2"></div>
<h3>最近 10 个交易日的信号</h3>
<p class="mut">可以和自己的实盘单子对照。收益已扣 0.2% 来回成本；“夜里涨跌/偏离”对 08:59 规则是合约相对昨天收盘的涨跌，对 09:31 规则是合约比正股贵（+）或便宜（−）多少。</p>
<div class="scroll tall" id="t-recent"></div>

<h2>机制：合约在 09:20 就动了，正股要到 09:30 才动</h2>
<p>每分钟的平均波动幅度。指数价格在港股交易时段跟随正股，休市时只缓慢跟随合约，所以它在 09:30 那一分钟一次性跳到开盘价；合约则在 09:20 竞价撮合那一分钟就明显放大，09:30 仍有一大段没走完。</p>
<figure id="f-profile">
  <div class="fig-title">每分钟平均波动（基点，所有标的、所有交易日）</div>
  <div class="legend"><span><i class="sw" style="background:var(--s1)"></i>合约</span><span><i class="sw" style="background:var(--s2)"></i>正股（币安指数价格）</span></div>
  <div class="chart" id="c-profile"></div>
  <div class="tip" hidden></div>
  <details class="tv"><summary>数据表</summary><div class="scroll tall" id="t-profile"></div></details>
</figure>

<h2>开盘跳空有多少被合约提前走掉</h2>
<p>横轴是正股真实的开盘跳空（相对前一交易日收盘），纵轴是合约在 09:29 之前已经走了多少。落在 45° 线上表示合约刚好走完；越过 45° 线外侧就是合约<b>走过头</b>。</p>
<figure id="f-scatter">
  <div class="fig-title">正股跳空 vs 合约开盘前已走（%）</div>
  <div class="legend" id="lg-scatter"></div>
  <div class="chart" id="c-scatter"></div>
  <div class="tip" hidden></div>
  <details class="tv"><summary>数据表</summary><div class="scroll tall" id="t-scatter"></div></details>
</figure>
<h3>分标的</h3>
<p class="mut">斜率 = 合约已走 ÷ 正股跳空的回归系数，100% 表示全部提前反映。</p>
<div class="scroll" id="t-pre"></div>

<h2>为什么按竞价方向追单会亏</h2>
<p>同样是“竞价显示要跌就做空”，结果取决于合约夜里是不是已经走过头。</p>
<div class="scroll" id="t-cats"></div>
<div class="callout"><b>判断标准要换：</b>不看“竞价价 vs 昨收”，看“竞价价 vs 合约现价”。合约已经比竞价走得更远时不要追；还没走到竞价价时才有空间。<span class="mut">09:21 进场一栏用的开盘价含开盘第一分钟走势，数字偏乐观，只看方向差异；09:31 进场一栏没有这个问题。</span></div>

<h2>开盘后：合约比正股贵就做空，持有到午休前后</h2>
<p>规则：09:31 时合约价比正股价高 0.3% 以上就做空合约，低 0.3% 以上就做多，11:59 平仓。下面的收益已扣成本。</p>
<div class="tiles" id="tiles"></div>
<p id="decomp"></p>
<figure id="f-sym">
  <div class="fig-title">分标的每笔净收益（基点，按实测价差扣成本）</div>
  <div class="legend"><span><i class="dot" style="background:var(--pos)"></i>盈利</span><span><i class="dot" style="background:var(--neg)"></i>亏损</span></div>
  <div class="chart" id="c-sym"></div>
  <div class="tip" hidden></div>
  <details class="tv"><summary>数据表</summary><div class="scroll" id="t-sym"></div></details>
</figure>
<h3>止损的代价</h3>
<p>这是均值回归交易，需要空间。止损越紧，被扫掉的好单越多。</p>
<div class="scroll" id="t-stops"></div>
<h3>参数是否挑出来的：前后两段分别看</h3>
<p class="mut" id="grid-note"></p>
<div class="scroll tall" id="t-grid"></div>
<h3>午休后 13:01</h3>
<p id="lunch"></p>

<h2>交易成本（逐笔成交实测）</h2>
<p>有效价差 = 5 秒内主动买入均价与主动卖出均价之差（含短期冲击）；深度为订单簿 ±0.2% / ±1% 内单侧挂单金额，取各交易日中位数。</p>
<div class="scroll" id="t-costs"></div>

<h2>怎么用</h2>
<p>开盘前填入券商看到的竞价相对昨收的涨跌幅，工具会算出合约还剩多少没走；09:31 之后运行，显示合约与正股的价差和建议。</p>
<pre>python -m jsq hk-now --auction ZHIPUUSDT=-2.3,MINIMAXUSDT=1.5 --proxy http://127.0.0.1:7890</pre>
<p>每天更新研究：<code>python -m jsq hk-study</code>。</p>

<h2>方法与局限</h2>
<ul class="key">
<li>数据：币安合约与指数价格 1 分钟 K 线、逐笔成交、订单簿深度（data.binance.vision）。指数价格在交易时段跟随正股，用来代表正股价格。</li>
<li>拿不到港交所真实的竞价成交价，开盘价用 09:30 那一分钟结束时的指数价格近似，里面混入了开盘第一分钟的走势。所以“09:21 按竞价方向进场”的绝对收益偏乐观，只能看相对差异。</li>
<li>开盘后价差收敛规则只用到 09:31 已知的信息，没有这个问题；参数在前后两段都为正。</li>
<li>港股合约 7–9 月才上线，样本 1–3 个月；成交清淡的标的实际滑点可能更大。不构成投资建议。</li>
</ul>
</main>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function S(tag, attrs, parent){const n=document.createElementNS(NS,tag);for(const k in attrs)n.setAttribute(k,attrs[k]);if(parent)parent.appendChild(n);return n;}
function H(tag, cls, text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}
const fmt = (v,d=0,sign=false)=> v==null||!isFinite(v) ? "–" : (sign&&v>0?"+":"")+Number(v).toFixed(d);
function ticks(lo,hi,n=5){const span=hi-lo||1,step0=span/n,mag=Math.pow(10,Math.floor(Math.log10(step0)));
  const step=[1,2,2.5,5,10].map(m=>m*mag).find(s=>s>=step0)||10*mag;const out=[];
  for(let v=Math.ceil(lo/step)*step;v<=hi+1e-9;v+=step)out.push(+v.toFixed(10));return out;}
function table(host, head, rows, leftCols=1){
  const t=H("table");const thr=H("tr");head.forEach((h,i)=>{const th=H("th",i<leftCols?"l":"",h);thr.appendChild(th)});
  const thead=H("thead");thead.appendChild(thr);t.appendChild(thead);const tb=H("tbody");
  rows.forEach(r=>{const tr=H("tr");r.forEach((c,i)=>{const td=H("td",i<leftCols?"l":"");
    if(c&&typeof c==="object"){td.textContent=c.t;if(c.cls)td.classList.add(c.cls);}else td.textContent=c;tr.appendChild(td)});tb.appendChild(tr)});
  t.appendChild(tb);host.replaceChildren(t);}
function signed(v,d=0){return {t:fmt(v,d,true),cls:v==null?"":(v>0?"posv":(v<0?"negv":""))};}
function showTip(fig, x, y, head, rows){
  const tip=fig.querySelector(".tip");tip.replaceChildren();tip.appendChild(H("div","h",head));
  rows.forEach(([color,label,value])=>{const r=H("div","r");const l=H("span","l");
    if(color){const k=H("i","sw");k.style.background=color;l.appendChild(k);}l.appendChild(document.createTextNode(label));
    r.appendChild(l);r.appendChild(H("span","v",value));tip.appendChild(r);});
  tip.hidden=false;const fw=fig.clientWidth,tw=tip.offsetWidth,th=tip.offsetHeight;
  let left=x+14;if(left+tw>fw-6)left=x-tw-14;if(left<6)left=6;let top=y-th-10;if(top<6)top=y+14;
  tip.style.left=left+"px";tip.style.top=top+"px";}
function hideTip(fig){fig.querySelector(".tip").hidden=true;}
function relPos(fig, ev){const r=fig.getBoundingClientRect();return [ev.clientX-r.left, ev.clientY-r.top];}

/* ---------- 摘要与表格 ---------- */
(function(){
  const m=D.meta, t=D.tiles, dec=D.decomp, cats=D.cats;
  document.getElementById("meta").textContent=`${m.symbols} 个港股合约 · ${m.start} 至 ${m.end} · ${m.obs} 个“标的×交易日” · 假设成本单边 ${m.cost_bps} 基点（手续费 ${m.fee_bps} + 滑点），实测成本见下文`;
  const over=cats.find(c=>c.key==="over");const O=D.overnight;
  const R=k=>O.rules.find(r=>r.rule.startsWith(k))||{};
  const r1=R("夜里涨 >1.0%：08:59 做空，09:31"),r11=R("夜里涨 >1.0%：08:59 做空，11:59"),r21=R("夜里涨 >2.0%：08:59 做空，11:59"),
        rm=R("夜里涨 1%~2%：08:59 做空，11:59"),rb=R("阿里美股"),
        cl=R("对照：夜里涨 >1%：08:59 追多"),cs=R("对照：夜里跌 >1%：08:59 追空");
  const X=D.excursion||{stops:[]},SG=s=>X.stops.find(r=>r.rule==="夜里涨 >1%：08:59 做空"&&r.exit==="11:59"&&r.stop===s)||{};
  const s1=SG(1),s3=SG(3),c13=(X.curve||[]).find(r=>r.rule==="夜里涨 >1%：08:59 做空"&&r.exit==="13:30")||{};
  document.getElementById("split-day").textContent=m.split;
  const items=[
    `<b>收盘后：</b>白天大跌的，合约收盘后两小时平均小幅反弹；白天大涨的，小幅回落。幅度只有 0.2%–0.3%，不够交易成本，到第二天早上白天涨跌已经不影响合约走势。`,
    `<b>夜里涨的靠不住，夜里跌的是真的：</b>合约到 08:59 比收盘涨超过 1% 的，开盘时平均吐回一半；夜里跌超过 1% 的，09:30 开盘那一下反弹约 0.4%，到中午又回到低位。跌后反弹的那种夜里上涨最容易过头。所以开盘前顺着夜里方向追单两头都亏：夜里涨了 08:59 追多，每笔 ${fmt(cl.exp,0,true)} 基点、胜率 ${cl.win}%；夜里跌了 08:59 追空，每笔 ${fmt(cs.exp,0,true)} 基点、胜率 ${cs.win}%。`,
    `<b>规则一：</b>08:59 合约比收盘涨 &gt;1% 就做空，拿到 11:59 平：每笔 ${fmt(r11.exp,0,true)} 基点，胜率 ${r11.win}%，后半段 ${fmt(r11.second,0,true)}；涨 &gt;2% 的每笔 ${fmt(r21.exp,0,true)}，涨 1%–2% 的 ${fmt(rm.exp,0,true)}。09:31 就平只有 ${fmt(r1.exp,0,true)}，后半段 ${fmt(r1.second,0,true)}：后来的回落多发生在开盘之后；拿到下午 13:30 每笔 ${fmt(c13.exp*100,0,true)}。止损别设近：1% 止损每笔降到 ${fmt(s1.exp*100,0,true)} 基点，3% 止损为 ${fmt(s3.exp*100,0,true)}。同一天几个合约一起出信号时基本同涨同跌，仓位要分摊。`,
    `<b>规则二：</b>09:31 合约比正股贵 0.3% 以上做空、拿到 11:59：每笔约 ${fmt(t.exp_real,0,true)} 基点，胜率 ${t.win}%。在智谱、MiniMax、小米等散户关注度高的标的上有效，腾讯、泡泡玛特、比亚迪上无效。${(()=>{const sd=(X.basis_sides||[]).find(r=>r.side==="多");return sd?`反过来合约比正股便宜去做多的 ${sd.n} 笔，前段每笔 ${fmt(sd.first,2,true)}%，后段只有 ${fmt(sd.second,2,true)}%，不建议做。`:"";})()}`,
    `<b>辅助：</b>阿里巴巴美股合约夜里涨（跌）超过 0.5%，开盘后顺着做到中午，每笔 ${fmt(rb.exp,0,true)} 基点，较弱。竞价阶段（09:00–09:29）合约平均回落约 0.15%：要买等竞价结束，要空在 09:00 前后。`,
  ];
  const ul=document.getElementById("summary");items.forEach(s=>{const li=document.createElement("li");li.innerHTML=s;ul.appendChild(li)});

  table(document.getElementById("t-pre"),["标的","交易日","平均跳空(基点)","08:59 已反映","09:29 已反映","09:29 剩余(基点)","方向一致"],
    D.prepricing.map(r=>[r.name,r.days,fmt(r.gap),fmt(r.p0859)+"%",fmt(r.p0929)+"%",fmt(r.left),fmt(r.same)+"%"]));
  table(document.getElementById("t-cats"),["情况","占比","天数","09:31 进场持有到 11:59","胜率","09:21 进场（偏乐观）","胜率"],
    cats.map(c=>[c.label,c.share+"%",c.n,signed(c.late_bps),c.late_win+"%",signed(c.early_bps),c.early_win+"%"]));
  const tl=document.getElementById("tiles");
  [["每笔净收益（实测成本）",fmt(t.exp_real,0,true)+" 基点",`按假设成本 ${fmt(t.exp_assumed,0,true)}`],
   ["t 值",fmt(t.t,1),"大于 2 才算显著"],["胜率",t.win+"%",`做空占 ${t.short_share}%`],["交易次数",String(t.trades),`${t.symbols} 个标的`]]
   .forEach(([a,b,c])=>{const d=H("div","tile");d.appendChild(H("div","lab",a));d.appendChild(H("div","val",b));d.appendChild(H("div","note",c));tl.appendChild(d)});
  document.getElementById("decomp").textContent=`毛收益 ${fmt(dec.gross,0)} 基点 = 正股同向回落 ${fmt(dec.stock,0)} + 合约相对正股的溢价收敛 ${fmt(dec.basis,0)}。持仓期间的不利波动：中位 ${fmt(dec.mae_med,0)} 基点，10% 的交易超过 ${fmt(dec.mae90,0)} 基点。`;
  table(document.getElementById("t-stops"),["止损","被止损比例","每笔净收益(基点)","t 值","胜率"],
    D.stops.map(r=>[r.stop,r.stopped+"%",signed(r.exp),fmt(r.t,1),r.win+"%"]));
  document.getElementById("grid-note").textContent=`以 ${m.split} 为界分成前后两段。规则最早按 09:31 / 0.3% / 11:59 设定，下表列出改变信号时间、阈值、平仓时间后的结果。`;
  table(document.getElementById("t-grid"),["信号","平仓","阈值","笔数","每笔(基点)","t","前段","后段","后段 t"],
    D.grid.map(r=>[r.signal,r.exit,r.th+"%",r.n,signed(r.exp),fmt(r.t,1),signed(r.first),signed(r.second),fmt(r.t2,1)]),2);
  const l=D.lunch.map(r=>`持有到 ${r.exit}：每笔 ${fmt(r.exp,0,true)} 基点（t=${fmt(r.t,1)}）`).join("；");
  document.getElementById("lunch").textContent=`午休期间合约和正股都只走了约 0.3%，合约也没有提前反映下午开盘（斜率约 0.1）。13:01 用同样规则：${l}，在前后两段不稳定，不建议单独交易。上午的单子可以拿过午休到 13:30 左右，结果与 11:59 平仓相近。`;
  if(D.costs.length){table(document.getElementById("t-costs"),["标的","时段","有效价差(基点)","10 分钟成交额(千美元)","单笔成交中位(美元)","±0.2% 深度(千美元)","±1% 深度(千美元)"],
    D.costs.map(r=>[r.name,r.window,fmt(r.spread,1),fmt(r.turnover),fmt(r.trade),fmt(r.depth02),fmt(r.depth1)]));}
  else document.getElementById("t-costs").textContent="逐笔成本数据尚未生成。";
})();

/* ---------- 收盘后 / 四种情况 / 规则 ---------- */
(function(){const O=D.overnight;
  const cell=v=>v&&v[0]!=null?{t:`${fmt(v[0],0,true)} / ${fmt(v[1],0)}%`,cls:v[0]>0?"posv":(v[0]<0?"negv":"")}:"–";
  table(document.getElementById("t-after"),["当天正股","天数","平均涨跌","18:00","21:30","次日 04:00","08:59","09:29"],
    O.after.map(r=>[r.bucket,r.n,fmt(r.day,1,true)+"%",cell(r["18:00"]),cell(r["21:30"]),cell(r["04:00"]),cell(r["08:59"]),cell(r["09:29"])]));
  document.getElementById("after-note").textContent="每格为“平均涨跌（基点）/ 上涨占比”。21:30–04:00 为美股交易时段（夏令时）。";
  table(document.getElementById("t-cases"),["情况","天数","白天涨跌","夜里合约","正股实际跳空","开盘那一下：顺夜里方向(+)/回落(-)","t","开盘后到中午：顺夜里方向(+)/回落(-)","t"],
    O.cases.map(r=>[r.case,r.n,fmt(r.day,1,true)+"%",fmt(r.night,2,true)+"%",fmt(r.gap,2,true)+"%",fmt(r.open,0,true)+" 基点",fmt(r.open_t,1),fmt(r.am,0,true)+" 基点",fmt(r.am_t,1)]));
  document.getElementById("beta-note").textContent=`夜里合约的涨跌里，跟着阿里巴巴美股合约走的部分（系数 ${fmt(O.beta,2)}）开盘后会继续（t=${fmt(O.mkt_t,1)}）；合约自己多走的部分开盘后不持续（t=${fmt(O.own_t,1)}）。`;
  table(document.getElementById("t-rules"),["规则","笔数","每笔(基点)","胜率","t","前段","后段","盈利标的"],
    O.rules.map(r=>[r.rule,r.n,signed(r.exp),r.win+"%",fmt(r.t,1),signed(r.first),signed(r.second),r.sym+"%"]));
  table(document.getElementById("t-paths"),["时点","夜里涨>1%（基点）","夜里跌>1%（基点）"],O.paths.map(p=>[p.t,fmt(p.up,0,true),fmt(p.down,0,true)]));
})();

/* ---------- 方向对不对 vs 能走多远 / 止损宽度 ---------- */
(function(){const X=D.excursion;if(!X)return;
  const vs=(a,b)=>({t:`${a}%（对照 ${b}%）`,cls:a>b+2?"posv":(a<b-2?"negv":"")});
  table(document.getElementById("t-touch"),["规则","平仓","笔数","方向对","方向错","没走出来","先到 +2R","t"],
    X.touch.map(r=>[r.rule,r.exit,r.n,vs(r.right,r.right_base),{t:`${r.wrong}%（对照 ${r.wrong_base}%）`,cls:r.wrong<r.wrong_base-2?"posv":(r.wrong>r.wrong_base+2?"negv":"")},
      r.none+"%",vs(r.two,r.two_base),fmt(r.t,1)]),2);
  const keys=[...new Set(X.stops.map(r=>r.rule+"|"+r.exit))],levels=[...new Set(X.stops.map(r=>r.stop))];
  table(document.getElementById("t-stopgrid"),["规则","平仓",...levels.map(s=>s==null?"不设止损":`止损 ${s}%`)],
    keys.map(k=>{const rs=X.stops.filter(r=>r.rule+"|"+r.exit===k);
      return [rs[0].rule,rs[0].exit,...levels.map(s=>{const r=rs.find(x=>x.stop===s);
        return r?{t:`${fmt(r.exp,2,true)}% · 胜率 ${r.win}% · 后段 ${fmt(r.second,2,true)}%`,cls:r.exp>0?"posv":(r.exp<0?"negv":"")}:"–";})];}),2);
  const base=X.stops.find(r=>r.rule==="夜里涨 >1%：08:59 做空"&&r.exit==="11:59"&&r.stop==null);
  const pc=v=>({t:fmt(v,2,true)+"%",cls:v>0?"posv":(v<0?"negv":"")});
  if(X.curve){
    table(document.getElementById("t-curve"),["规则","平仓","笔数","每笔平均","胜率","前段","后段","按天算的 t"],
      X.curve.map(r=>[r.rule,r.exit,r.n,pc(r.exp),r.win+"%",pc(r.first),pc(r.second),fmt(r.day_t,1)]),2);
    table(document.getElementById("t-bysym2"),["规则","合约","笔数","拿到 11:59","胜率","拿到 13:30","后段（11:59）"],
      X.bysym.map(r=>[r.rule,r.name,r.n,pc(r.e1159),r.w1159+"%",pc(r.e1330),pc(r.second)]),2);
    table(document.getElementById("t-recent"),["日期","合约","规则","方向","夜里涨跌/偏离","拿到 11:59","拿到 13:30"],
      X.recent.map(r=>[r.day,r.name,r.rule,r.side,fmt(r.move,2,true)+"%",pc(r.r1159),pc(r.r1330)]),3);
  }
  if(base)document.getElementById("stop-note").innerHTML=`<b>结论：</b>夜里涨的单子方向是对的，但开盘前后来回扫得很厉害，1% 的止损经常先被打掉、之后价格才往下走，所以止损越近赚得越少。不设止损最好，但风险大：最差一次亏 ${fmt(Math.abs(base.worst),1)}%，10% 的单子中途逆向超过 ${fmt(base.adv90,1)}%。实盘建议设 3% 左右的宽止损、杠杆别开大。`;
})();
function drawPaths(){
  const fig=document.getElementById("f-paths"),host=document.getElementById("c-paths"),P=D.overnight.paths;
  const W=Math.max(300,host.clientWidth),Hh=Math.round(Math.min(320,Math.max(240,W*0.42)));
  const narrow=W<560,m={l:44,r:narrow?44:64,t:22,b:narrow?46:30},iw=W-m.l-m.r,ih=Hh-m.t-m.b;
  const vals=P.flatMap(p=>[p.up,p.down]);let tk=ticks(Math.min(0,...vals),Math.max(0,...vals),5);
  const lo=Math.min(tk[0],...vals),hi=Math.max(tk[tk.length-1],...vals);
  const x=i=>m.l+i*(iw/(P.length-1)),y=v=>m.t+(hi-v)/(hi-lo)*ih;
  const svg=S("svg",{width:W,height:Hh,role:"img","aria-label":"夜里涨与夜里跌两组合约的平均走势",tabindex:0});
  tk.forEach(v=>{S("line",{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css("--grid"),"stroke-width":1},svg);
    const tx=S("text",{x:m.l-6,y:y(v)+4,"text-anchor":"end","font-size":11,fill:css("--muted")},svg);tx.textContent=v;});
  S("line",{x1:m.l,x2:W-m.r,y1:y(0),y2:y(0),stroke:css("--axis"),"stroke-width":1},svg);
  const io=P.findIndex(p=>p.t.startsWith("09:29")),ia=P.findIndex(p=>p.t.startsWith("09:31"));
  if(io>=0&&ia>=0){S("rect",{x:x(io),y:m.t,width:x(ia)-x(io),height:ih,fill:css("--tint2")},svg);
    const tx=S("text",{x:(x(io)+x(ia))/2,y:m.t-8,"text-anchor":"middle","font-size":11,fill:css("--ink2")},svg);tx.textContent="开盘";}
  P.forEach((p,i)=>{const lab=p.t.split(" ")[narrow?0:0];const tx=S("text",{x:x(i),y:Hh-(narrow?30:10),"text-anchor":narrow?"end":"middle",
    "font-size":10.5,fill:css("--muted"),transform:narrow?`rotate(-40 ${x(i)} ${Hh-30})`:""},svg);tx.textContent=narrow?lab.replace("收盘","收"):p.t.replace(" 美股开盘","").replace(" 美股收盘","").replace(" 撮合","").replace(" 开盘后","");});
  [["up","--s1","夜里涨"],["down","--s2","夜里跌"]].forEach(([k,c,lab])=>{S("path",{d:P.map((p,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(p[k]).toFixed(1)).join(""),
      fill:"none",stroke:css(c),"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"},svg);
    const last=P[P.length-1][k];S("circle",{cx:x(P.length-1),cy:y(last),r:4,fill:css(c),stroke:css("--surface"),"stroke-width":2},svg);
    const tx=S("text",{x:x(P.length-1)+8,y:y(last)+4,"font-size":12,fill:css("--ink")},svg);tx.textContent=fmt(last,0,true);});
  const cross=S("line",{y1:m.t,y2:m.t+ih,stroke:css("--axis"),"stroke-width":1,visibility:"hidden"},svg);
  let cur=io>=0?io:0;
  function show(i){cur=i;const p=P[i];cross.setAttribute("x1",x(i));cross.setAttribute("x2",x(i));cross.setAttribute("visibility","visible");
    const fr=fig.getBoundingClientRect(),sr=svg.getBoundingClientRect();
    showTip(fig,x(i)+(sr.left-fr.left),m.t+(sr.top-fr.top)+10,p.t,[[css("--s1"),"夜里涨 >1%",fmt(p.up,0,true)+" 基点"],[css("--s2"),"夜里跌 >1%",fmt(p.down,0,true)+" 基点"]]);}
  function hide(){cross.setAttribute("visibility","hidden");hideTip(fig);}
  svg.addEventListener("pointermove",ev=>{const r=svg.getBoundingClientRect();show(Math.max(0,Math.min(P.length-1,Math.round((ev.clientX-r.left-m.l)/(iw/(P.length-1))))));});
  svg.addEventListener("pointerleave",hide);svg.addEventListener("focus",()=>show(cur));svg.addEventListener("blur",hide);
  svg.addEventListener("keydown",ev=>{if(ev.key==="ArrowRight"){show(Math.min(P.length-1,cur+1));ev.preventDefault();}if(ev.key==="ArrowLeft"){show(Math.max(0,cur-1));ev.preventDefault();}});
  host.replaceChildren(svg);
}

/* ---------- 图 1：分钟波动 ---------- */
function drawProfile(){
  const fig=document.getElementById("f-profile"),host=document.getElementById("c-profile"),P=D.profile;
  const W=Math.max(300,host.clientWidth),Hh=Math.round(Math.min(300,Math.max(220,W*0.42)));
  const m={l:40,r:16,t:22,b:28},iw=W-m.l-m.r,ih=Hh-m.t-m.b;
  const ymax=Math.max(...P.map(p=>Math.max(p.perp,p.index)));let yt=ticks(0,ymax,4);const step=yt[1]-yt[0];
  const ytop=Math.ceil(ymax*1.12/step)*step;yt=ticks(0,ytop,Math.round(ytop/step));
  const x=i=>m.l+i*(iw/(P.length-1)),y=v=>m.t+ih-(v/ytop)*ih;
  const svg=S("svg",{width:W,height:Hh,role:"img","aria-label":"每分钟平均波动，合约与正股",tabindex:0});
  yt.forEach(v=>{S("line",{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css("--grid"),"stroke-width":1},svg);
    const tx=S("text",{x:m.l-6,y:y(v)+4,"text-anchor":"end","font-size":11,fill:css("--muted")},svg);tx.textContent=v;});
  P.forEach((p,i)=>{if(p.t.endsWith(":00")||p.t.endsWith(":30")){const tx=S("text",{x:x(i),y:Hh-8,"text-anchor":"middle","font-size":11,fill:css("--muted")},svg);tx.textContent=p.t;}});
  [["09:20","09:20 撮合"],["09:30","09:30 开盘"]].forEach(([t,lab],k)=>{const i=P.findIndex(p=>p.t===t);if(i<0)return;
    S("line",{x1:x(i),x2:x(i),y1:m.t,y2:m.t+ih,stroke:css("--axis"),"stroke-width":1},svg);
    const tx=S("text",{x:x(i)+(k?4:-4),y:m.t-8,"text-anchor":k?"start":"end","font-size":11,fill:css("--ink2")},svg);tx.textContent=lab;});
  S("line",{x1:m.l,x2:W-m.r,y1:m.t+ih,y2:m.t+ih,stroke:css("--axis"),"stroke-width":1},svg);
  [["perp","--s1"],["index","--s2"]].forEach(([k,c])=>{S("path",{d:P.map((p,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(p[k]).toFixed(1)).join(""),
    fill:"none",stroke:css(c),"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"},svg);});
  const pk=P.findIndex(p=>p.t==="09:30");
  if(pk>=0){[["index","正股","--s2"],["perp","合约","--s1"]].forEach(([k,lab])=>{const tx=S("text",{x:x(pk)+8,y:y(P[pk][k])+4,"font-size":12,fill:css("--ink")},svg);tx.textContent=`${lab} ${fmt(P[pk][k])}`;});}
  const cross=S("line",{y1:m.t,y2:m.t+ih,stroke:css("--axis"),"stroke-width":1,visibility:"hidden"},svg);
  const dots=[["perp","--s1"],["index","--s2"]].map(([k,c])=>S("circle",{r:4,fill:css(c),stroke:css("--surface"),"stroke-width":2,visibility:"hidden"},svg));
  let cur=pk>=0?pk:0;
  function show(i){cur=i;const p=P[i];cross.setAttribute("x1",x(i));cross.setAttribute("x2",x(i));cross.setAttribute("visibility","visible");
    dots[0].setAttribute("cx",x(i));dots[0].setAttribute("cy",y(p.perp));dots[1].setAttribute("cx",x(i));dots[1].setAttribute("cy",y(p.index));
    dots.forEach(d=>d.setAttribute("visibility","visible"));
    const fr=fig.getBoundingClientRect(),sr=svg.getBoundingClientRect();
    showTip(fig,x(i)+(sr.left-fr.left),y(Math.max(p.perp,p.index))+(sr.top-fr.top),`${p.t}（香港时间）`,
      [[css("--s1"),"合约",fmt(p.perp,1)+" 基点"],[css("--s2"),"正股",fmt(p.index,1)+" 基点"]]);}
  function hide(){cross.setAttribute("visibility","hidden");dots.forEach(d=>d.setAttribute("visibility","hidden"));hideTip(fig);}
  svg.addEventListener("pointermove",ev=>{const r=svg.getBoundingClientRect();const px=ev.clientX-r.left;
    const i=Math.max(0,Math.min(P.length-1,Math.round((px-m.l)/(iw/(P.length-1)))));show(i);});
  svg.addEventListener("pointerleave",hide);svg.addEventListener("focus",()=>show(cur));svg.addEventListener("blur",hide);
  svg.addEventListener("keydown",ev=>{if(ev.key==="ArrowRight"){show(Math.min(P.length-1,cur+1));ev.preventDefault();}
    if(ev.key==="ArrowLeft"){show(Math.max(0,cur-1));ev.preventDefault();}});
  host.replaceChildren(svg);
}
table(document.getElementById("t-profile"),["时间","合约(基点)","正股(基点)"],D.profile.map(p=>[p.t,fmt(p.perp,1),fmt(p.index,1)]));

/* ---------- 图 2：散点 ---------- */
const CAT={over:["合约走过头","--s2"],under:["合约还没走够","--s1"],opposite:["合约方向相反","--s3"]};
(function(){const lg=document.getElementById("lg-scatter");D.cats.forEach(c=>{const s=H("span");const d=H("i","dot");d.style.background=`var(${CAT[c.key][1]})`;
  s.appendChild(d);s.appendChild(document.createTextNode(`${c.label} ${c.share}%`));lg.appendChild(s);});
  const s=H("span");const k=H("i","sw");k.style.background="var(--muted)";s.appendChild(k);s.appendChild(document.createTextNode("45° 线：合约刚好走完"));lg.appendChild(s);})();
function drawScatter(){
  const fig=document.getElementById("f-scatter"),host=document.getElementById("c-scatter"),pts=D.scatter;
  const W=Math.max(300,host.clientWidth),Hh=Math.round(Math.min(460,Math.max(280,W*0.62)));
  const m={l:44,r:12,t:12,b:36},iw=W-m.l-m.r,ih=Hh-m.t-m.b;
  const ext=Math.max(...pts.map(p=>Math.max(Math.abs(p.x),Math.abs(p.y))));const tk=ticks(-ext,ext,6);const lo=Math.min(tk[0],-ext),hi=Math.max(tk[tk.length-1],ext);
  const x=v=>m.l+(v-lo)/(hi-lo)*iw,y=v=>m.t+ih-(v-lo)/(hi-lo)*ih;
  const svg=S("svg",{width:W,height:Hh,role:"img","aria-label":"正股跳空与合约开盘前已走的散点图"});
  tk.forEach(v=>{S("line",{x1:x(v),x2:x(v),y1:m.t,y2:m.t+ih,stroke:css("--grid"),"stroke-width":1},svg);
    S("line",{x1:m.l,x2:m.l+iw,y1:y(v),y2:y(v),stroke:css("--grid"),"stroke-width":1},svg);
    let t=S("text",{x:x(v),y:Hh-18,"text-anchor":"middle","font-size":11,fill:css("--muted")},svg);t.textContent=v;
    t=S("text",{x:m.l-6,y:y(v)+4,"text-anchor":"end","font-size":11,fill:css("--muted")},svg);t.textContent=v;});
  S("line",{x1:x(0),x2:x(0),y1:m.t,y2:m.t+ih,stroke:css("--axis"),"stroke-width":1},svg);
  S("line",{x1:m.l,x2:m.l+iw,y1:y(0),y2:y(0),stroke:css("--axis"),"stroke-width":1},svg);
  S("line",{x1:x(lo),y1:y(lo),x2:x(hi),y2:y(hi),stroke:css("--muted"),"stroke-width":1},svg);
  let t=S("text",{x:m.l+iw/2,y:Hh-2,"text-anchor":"middle","font-size":11.5,fill:css("--ink2")},svg);t.textContent="正股开盘跳空（%）";
  t=S("text",{x:12,y:m.t+ih/2,"text-anchor":"middle","font-size":11.5,fill:css("--ink2"),transform:`rotate(-90 12 ${m.t+ih/2})`},svg);t.textContent="合约 09:29 前已走（%）";
  const g=S("g",{},svg);const nodes=pts.map(p=>S("circle",{cx:x(p.x),cy:y(p.y),r:4,fill:css(CAT[p.c][1]),stroke:css("--surface"),"stroke-width":1.5},g));
  const hl=S("circle",{r:6,fill:"none",stroke:css("--ink"),"stroke-width":1.5,visibility:"hidden"},svg);
  svg.addEventListener("pointermove",ev=>{const r=svg.getBoundingClientRect();const px=ev.clientX-r.left,py=ev.clientY-r.top;
    let best=-1,bd=24*24;pts.forEach((p,i)=>{const dx=x(p.x)-px,dy=y(p.y)-py,dd=dx*dx+dy*dy;if(dd<bd){bd=dd;best=i;}});
    if(best<0){hl.setAttribute("visibility","hidden");hideTip(fig);return;}const p=pts[best];
    hl.setAttribute("cx",x(p.x));hl.setAttribute("cy",y(p.y));hl.setAttribute("visibility","visible");
    const fr=fig.getBoundingClientRect();showTip(fig,x(p.x)+(r.left-fr.left),y(p.y)+(r.top-fr.top),`${p.s} · ${p.d}`,
      [[null,"正股跳空",fmt(p.x,2,true)+"%"],[null,"合约已走",fmt(p.y,2,true)+"%"],[css(CAT[p.c][1]),CAT[p.c][0],""]]);});
  svg.addEventListener("pointerleave",()=>{hl.setAttribute("visibility","hidden");hideTip(fig);});
  host.replaceChildren(svg);
}
table(document.getElementById("t-scatter"),["标的","日期","正股跳空(%)","合约已走(%)","情况"],D.scatter.map(p=>[p.s,p.d,fmt(p.x,2,true),fmt(p.y,2,true),CAT[p.c][0]]),2);

/* ---------- 图 3：分标的 ---------- */
function drawSym(){
  const fig=document.getElementById("f-sym"),host=document.getElementById("c-sym"),R=D.by_symbol;
  const W=Math.max(300,host.clientWidth),row=30,lab=Math.min(150,Math.max(96,W*0.22)),Hh=R.length*row+30;
  const m={l:lab,r:56,t:6,b:24},iw=W-m.l-m.r;
  const vals=R.map(r=>r.real);const lo=Math.min(0,...vals),hi=Math.max(0,...vals);const tk=ticks(lo,hi,4);
  const a=Math.min(lo,tk[0]),b=Math.max(hi,tk[tk.length-1]);const x=v=>m.l+(v-a)/(b-a)*iw;
  const svg=S("svg",{width:W,height:Hh,role:"img","aria-label":"分标的每笔净收益"});
  tk.forEach(v=>{S("line",{x1:x(v),x2:x(v),y1:m.t,y2:Hh-m.b,stroke:css("--grid"),"stroke-width":1},svg);
    const t=S("text",{x:x(v),y:Hh-6,"text-anchor":"middle","font-size":11,fill:css("--muted")},svg);t.textContent=v;});
  S("line",{x1:x(0),x2:x(0),y1:m.t,y2:Hh-m.b,stroke:css("--axis"),"stroke-width":1},svg);
  R.forEach((r,i)=>{const cy=m.t+i*row+row/2,bh=16,x0=x(0),x1=x(r.real),w=Math.abs(x1-x0),neg=r.real<0,rad=Math.min(4,w);
    let t=S("text",{x:m.l-10,y:cy+4,"text-anchor":"end","font-size":12.5,fill:css("--ink")},svg);t.textContent=r.name;
    if(r.weak){t.setAttribute("fill",css("--muted"));}
    const left=neg?x1:x0,top=cy-bh/2;
    const d=neg?`M${x0},${top}H${left+rad}Q${left},${top} ${left},${top+rad}V${top+bh-rad}Q${left},${top+bh} ${left+rad},${top+bh}H${x0}Z`
               :`M${x0},${top}H${x1-rad}Q${x1},${top} ${x1},${top+rad}V${top+bh-rad}Q${x1},${top+bh} ${x1-rad},${top+bh}H${x0}Z`;
    const bar=S("path",{d,fill:css(neg?"--neg":"--pos"),tabindex:0,role:"img","aria-label":`${r.name} ${fmt(r.real,0,true)} 基点`},svg);
    const hit=S("rect",{x:m.l,y:cy-row/2,width:iw,height:row,fill:"transparent"},svg);
    t=S("text",{x:neg?x1-6:x1+6,y:cy+4,"text-anchor":neg?"end":"start","font-size":12,fill:css("--ink2")},svg);t.textContent=fmt(r.real,0,true);
    const show=()=>{bar.setAttribute("opacity",.8);const fr=fig.getBoundingClientRect(),sr=svg.getBoundingClientRect();
      showTip(fig,Math.max(x0,x1)+(sr.left-fr.left),cy+(sr.top-fr.top),r.name+(r.weak?"（历史上此规则无效）":""),
        [[null,"每笔净收益",fmt(r.real,0,true)+" 基点"],[null,"交易次数",String(r.n)],[null,"胜率",r.win+"%"],
         [null,"不利波动 90% 分位",fmt(r.mae90,0)+" 基点"],[null,"来回成本",fmt(r.real_cost,1)+" 基点"]]);};
    const hide=()=>{bar.setAttribute("opacity",1);hideTip(fig);};
    [hit,bar].forEach(n=>{n.addEventListener("pointerenter",show);n.addEventListener("pointerleave",hide);});
    bar.addEventListener("focus",show);bar.addEventListener("blur",hide);});
  host.replaceChildren(svg);
}
table(document.getElementById("t-sym"),["标的","交易次数","每笔净收益(实测成本)","每笔净收益(假设成本)","来回成本(基点)","胜率","不利波动90%(基点)"],
  D.by_symbol.map(r=>[r.name+(r.weak?"（历史无效）":""),r.n,signed(r.real),signed(r.assumed),fmt(r.real_cost,1),r.win+"%",fmt(r.mae90)]));

function drawAll(){drawPaths();drawProfile();drawScatter();drawSym();}
drawAll();
let rz;new ResizeObserver(()=>{clearTimeout(rz);rz=setTimeout(drawAll,120);}).observe(document.querySelector("main"));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",drawAll);
new MutationObserver(drawAll).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
</script>
"""


def build_html(data: dict, out: Path, fragment: bool = True) -> Path:
    body = PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    if not fragment:
        body = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">' + body + "</html>")
    out = Path(out)
    out.write_text(body, encoding="utf-8")
    return out
