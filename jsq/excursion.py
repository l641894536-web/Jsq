"""方向判断 vs 能走多远：按持仓期间的最大浮盈 / 最大浮亏（MFE / MAE）拆开评价开仓信号。

一般的回测把“方向对不对”和“出场设得对不对”混在一起：止损 1R、目标 2R，走到 2R 的少就判失败，
可能方向是对的，只是目标定远了。这里对每次开仓只看之后的价格路径：
  * 1R = 止损距离。记录各档浮盈（+0.5R … +3R）和浮亏（-0.5R、-1R、-2R）第一次被碰到的时间
  * 方向对 = +1R 比 -1R 先到；方向错 = -1R 先到；窗口内两边都没碰到 = 没走出来
    同一根 K 线两边都碰到时算 -1R 先到（保守）
  * 对照：同一时刻反方向开仓。两者平均就是“同一时刻随机猜方向”，波动大小完全一样，
    方向对的比例比对照高多少，才是信号真正的判断力（价格纯随机游走时对照约 50%）
  * 目标网格：止损固定 1R，目标 0.5R~3R，窗口结束仍没碰到就按收盘平仓，算扣费后每笔期望（R）
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

FAV = (0.5, 0.8, 1.0, 1.5, 2.0, 3.0)    # 浮盈档位（R），同时是目标网格
ADV = (0.5, 1.0, 2.0, 3.0)              # 浮亏档位（R）
HK_COST_RT = 0.002                      # 港股合约来回成本（与 hk_overnight 一致）


def touches(hi: np.ndarray, lo: np.ndarray, entry, side, r, end_px) -> pd.DataFrame:
    """hi/lo：N×H，开仓后每根 K 线的最高/最低价（缺失为 NaN）；entry/side/r/end_px：每笔的成交价、
    方向（±1）、1R 对应的价格距离、窗口最后一根 K 线的收盘价。
    返回每笔：f{L}/a{L} = 浮盈/浮亏第一次达到 L 倍 R 的 K 线序号（没达到为 H），mfe/mae（R），
    mfe_pre = 碰到 -1R 之前的最大浮盈，end = 窗口结束时的盈亏（R）。"""
    e, s, rr = (np.asarray(x, float)[:, None] for x in (entry, side, r))
    up, dn = (hi - e) / rr, (e - lo) / rr
    fav = np.where(s > 0, up, dn)
    adv = np.where(s > 0, dn, up)
    fav = np.maximum.accumulate(np.where(np.isnan(fav), -np.inf, fav), axis=1)
    adv = np.maximum.accumulate(np.where(np.isnan(adv), -np.inf, adv), axis=1)
    n, H = hi.shape

    def first(run, L):
        hit = run >= L
        return np.where(hit.any(axis=1), hit.argmax(axis=1), H)

    out = {f"f{L}": first(fav, L) for L in FAV}
    out.update({f"a{L}": first(adv, L) for L in ADV})
    a1 = out["a1.0"]
    # 碰到 -1R 那根 K 线里的高点未必在低点之前，只算到前一根
    pre = np.where(a1 < H, fav[np.arange(n), np.maximum(a1 - 1, 0)], fav[:, -1])
    pre = np.where(a1 == 0, 0.0, pre)
    out.update(mfe=np.maximum(fav[:, -1], 0.0), mae=np.maximum(adv[:, -1], 0.0), mfe_pre=np.maximum(pre, 0.0),
               end=s[:, 0] * (np.asarray(end_px, float) - e[:, 0]) / rr[:, 0])
    t = pd.DataFrame(out)
    t.attrs["H"] = H
    return t


def outcome(t: pd.DataFrame, k: float, s: float = 1.0) -> np.ndarray:
    """止损 sR、目标 kR、窗口结束按收盘平仓时每笔的毛收益（R）。"""
    H = t.attrs["H"]
    tf, ta = t[f"f{k}"].to_numpy(), t[f"a{s}"].to_numpy()
    win = (tf < ta) & (tf < H)
    loss = (ta <= tf) & (ta < H)
    return np.where(win, k, np.where(loss, -s, t["end"].to_numpy()))


def _flags(t: pd.DataFrame) -> dict[str, np.ndarray]:
    H = t.attrs["H"]
    f = {L: t[f"f{L}"].to_numpy() for L in FAV}
    a = {L: t[f"a{L}"].to_numpy() for L in ADV}
    right = (f[1.0] < a[1.0]) & (f[1.0] < H)
    wrong = (a[1.0] <= f[1.0]) & (a[1.0] < H)
    return {"right": right, "wrong": wrong, "none": ~right & ~wrong,
            "half": (f[0.5] < a[1.0]) & (f[0.5] < H),
            "two": (f[2.0] < a[1.0]) & (f[2.0] < H),
            "deep": (a[2.0] < f[1.0]) & (a[2.0] < H),
            # 先到 +0.5R，又在 +1R 之前打回 -1R：方向看着对、没走出来又亏掉
            "gave_back": (f[0.5] < a[1.0]) & wrong}


def _t(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return np.nan
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(len(x))) if sd > 0 else 0.0


def profile(sig: pd.DataFrame, opp: pd.DataFrame, cost_r, half: np.ndarray | None = None) -> dict:
    """sig：信号方向的 touches；opp：同一批开仓反方向的 touches；cost_r：每笔来回成本（R）；
    half：True = 后半段（检查最佳目标在前后两段是否一致）。"""
    cost_r = np.broadcast_to(np.asarray(cost_r, float), (len(sig),))
    fs, fo = _flags(sig), _flags(opp)
    row = {"n": len(sig), "cost_R": float(np.mean(cost_r))}
    for k in fs:
        row[k] = float(fs[k].mean())
        row[f"{k}_base"] = float((fs[k].mean() + fo[k].mean()) / 2)
    row["right_t"] = _t(fs["right"].astype(float) - fo["right"].astype(float))
    st = fs["wrong"]
    row["mfe_pre_med"] = float(np.median(sig["mfe_pre"].to_numpy()[st])) if st.any() else np.nan
    row["mfe_med"], row["mae_med"] = float(sig["mfe"].median()), float(sig["mae"].median())
    best, best_e = None, -np.inf
    for k in FAV:
        g = outcome(sig, k) - cost_r
        b = (outcome(sig, k) + outcome(opp, k)) / 2 - cost_r
        row[f"E{k}"], row[f"B{k}"], row[f"t{k}"] = float(g.mean()), float(b.mean()), _t(g)
        if half is not None and half.any() and (~half).any():
            row[f"E{k}_1"], row[f"E{k}_2"] = float(g[~half].mean()), float(g[half].mean())
        if g.mean() > best_e:
            best, best_e = k, g.mean()
    row["best_k"], row["best_E"] = best, float(best_e)
    return row


# 不设止损，看整条路怎么走：±2R 谁先到，到 -2R 之前有没有先往有利方向走过 0.8R
PATHS = {"trend": "一路顺：先到 +2R",
         "fake": "先顺后大逆：先到 +0.8R，没到 +2R 就跌到 -2R",
         "direct": "直接逆：没到 +0.8R 就先到 -2R",
         "flat": "没走出来：±2R 都没到"}
END_BINS = [(-np.inf, -2.0, "le-2"), (-2.0, -0.5, "-2~-0.5"), (-0.5, 0.5, "flat"), (0.5, 2.0, "0.5~2"), (2.0, np.inf, "ge2")]


def path_flags(t: pd.DataFrame) -> dict[str, np.ndarray]:
    """四类互斥（trend/fake/direct/flat 加起来 = 1）；fake3/direct3 为跌到 -3R 的同类。同一根 K 线两边都碰到算先亏。"""
    H = t.attrs["H"]
    f8, f2 = t["f0.8"].to_numpy(), t["f2.0"].to_numpy()
    a2, a3 = t["a2.0"].to_numpy(), t["a3.0"].to_numpy()
    hit2 = (a2 <= f2) & (a2 < H)
    hit3 = (a3 <= f2) & (a3 < H)
    return {"trend": (f2 < a2) & (f2 < H), "fake": hit2 & (f8 < a2), "direct": hit2 & (a2 <= f8),
            "flat": (a2 >= H) & (f2 >= H), "fake3": hit3 & (f8 < a3), "direct3": hit3 & (a3 <= f8)}


def path_profile(sig: pd.DataFrame, opp: pd.DataFrame, cost_r, ends: dict | None = None) -> dict:
    """路径分类与随机对照（同一时刻反方向的平均）；最后停在哪：窗口结束时盈亏的分布。
    ends：{持有小时: 每笔信号方向的盈亏（R，未扣费）}，看 1 天 / 3 天 / 7 天后各自平均停在哪。"""
    cost_r = np.broadcast_to(np.asarray(cost_r, float), (len(sig),))
    ps, po = path_flags(sig), path_flags(opp)
    row = {}
    for k in ps:
        row[f"p_{k}"] = float(ps[k].mean())
        row[f"p_{k}_base"] = float((ps[k].mean() + po[k].mean()) / 2)
    score = lambda f: f["trend"].astype(float) - f["fake"] - f["direct"]
    row["path_t"] = _t(score(ps) - score(po))       # 好路径多、坏路径少，相对随机是否显著
    e = sig["end"].to_numpy()
    for lo, hi, lab in END_BINS:
        sig_share = ((e > lo) & (e <= hi)).mean() if hi != np.inf else (e > lo).mean()
        opp_share = ((-e > lo) & (-e <= hi)).mean() if hi != np.inf else (-e > lo).mean()
        row[f"end_{lab}"], row[f"end_{lab}_base"] = float(sig_share), float((sig_share + opp_share) / 2)
    for k in (2.0, 3.0):                            # 止损 2R、止盈 kR（窗口结束按收盘平）
        o = outcome(sig, k, 2.0) - cost_r
        row[f"b{k:g}x2"], row[f"b{k:g}x2_t"] = float(o.mean()), _t(o)
    for h, x in (ends or {}).items():
        x = np.asarray(x, float)
        ok = np.isfinite(x)
        net = x[ok] - cost_r[ok]
        row[f"hold{h}"] = float(net.mean()) if ok.any() else np.nan
        row[f"hold{h}_up"] = float((x[ok] > 0).mean()) if ok.any() else np.nan
        row[f"hold{h}_t"] = _t(net)
    return row


# ----------------------------------------------------------------------------- 港股合约（1 分钟）

def hk_paths(p: dict, days, entry_hm: str, exit_hm: str):
    """hk.panel 的面板 → entry_hm 收盘成交、之后到 exit_hm 每分钟的最高/最低价。"""
    t = pd.date_range(f"2000-01-01 {entry_hm}", f"2000-01-01 {exit_hm}", freq="min")
    cols = [x.strftime("%H:%M") for x in t[1:]]
    days = [d for d in days if d in p["close"].index]
    c = p["close"].reindex(columns=[entry_hm] + cols)
    entry = c.loc[days, entry_hm].to_numpy(float)
    hi = p["high"].reindex(columns=cols).loc[days].to_numpy(float)
    lo = p["low"].reindex(columns=cols).loc[days].to_numpy(float)
    end = c.loc[days, exit_hm].to_numpy(float)
    return days, entry, hi, lo, end


HK_RULES = [  # 名称, 开仓时刻, 平仓时刻
    ("夜里涨 >1%：08:59 做空", "08:59", ("09:31", "11:59")),
    ("夜里涨 >2%：08:59 做空", "08:59", ("09:31", "11:59")),
    ("夜里涨 1%~2%：08:59 做空", "08:59", ("09:31", "11:59")),
    ("夜里跌 >1%：08:59 追空", "08:59", ("09:31", "11:59")),
    ("09:31 合约偏离正股 >0.3%：反向做", "09:31", ("11:59",)),
]


def _hk_sides(p: dict, o: pd.DataFrame) -> dict[str, pd.Series]:
    """一个标的：规则名 → 各交易日的开仓方向（±1）。o 为该标的的 hk_overnight.overnight_table。"""
    n = o.set_index("next_day")["pm_08:59"]
    basis = p["close"]["09:31"] / p["index"]["09:31"] - 1 if "09:31" in p["close"] else pd.Series(dtype=float)
    picks = [-np.sign(n[n > 0.01]), -np.sign(n[n > 0.02]), -np.sign(n[(n > 0.01) & (n <= 0.02)]),
             np.sign(n[n < -0.01]), -np.sign(basis[basis.abs() > 0.003])]
    return {r[0]: s.dropna() for r, s in zip(HK_RULES, picks)}


def hk_inputs(data_dir: Path, symbols=None):
    """与 hk_report.build_data 相同的面板、收盘→次日开盘表（去掉 ±15% 极端日）和前后段分界日。"""
    from . import hk
    from . import hk_overnight as ho
    d = Path(data_dir) / "hk1m"
    syms = [s for s in (symbols or hk.HK_SYMBOLS) if (d / f"{s}_1m_klines.csv").exists()]
    P, O = {}, []
    for s in syms:
        df = hk.load(s, d)
        P[s] = hk.panel(df, start="08:50")
        O.append(ho.overnight_table(df))
    O = pd.concat(O, ignore_index=True)
    O = O[O["day_chg"].abs() <= 0.15].reset_index(drop=True)
    days = sorted({x for p in P.values() for x in p["close"].index})
    return P, O, days[len(days) // 2]


def _hk_gather(P: dict, O: pd.DataFrame):
    """(规则, 开仓, 平仓) → 合并所有标的的 day / entry / side / hi / lo / end。"""
    acc: dict[tuple, list] = {}
    for s, p in P.items():
        sides = _hk_sides(p, O[O["symbol"] == s])
        for name, hm, exits in HK_RULES:
            sd = sides[name]
            for ex_hm in exits:
                days, entry, hi, lo, end = hk_paths(p, list(sd.index), hm, ex_hm)
                if len(days):
                    acc.setdefault((name, hm, ex_hm), []).append(
                        (np.asarray(days), entry, sd.loc[days].to_numpy(float), hi, lo, end))
    out = {}
    for key, lst in acc.items():
        day, entry, side, hi, lo, end = (np.concatenate([x[i] for x in lst]) if i not in (3, 4)
                                         else np.vstack([x[i] for x in lst]) for i in range(6))
        ok = np.isfinite(entry) & np.isfinite(end)
        out[key] = (day[ok], entry[ok], side[ok], hi[ok], lo[ok], end[ok])
    return out


def hk_study(P: dict, O: pd.DataFrame, split: str, r_pct: float = 0.01, cost_rt: float = HK_COST_RT,
             gathered=None) -> pd.DataFrame:
    """港股合约几条规则的方向判断与目标网格（对照 = 同一时刻反方向）。1R = 开仓价的 r_pct。"""
    rows = []
    for (name, hm, ex_hm), (day, entry, side, hi, lo, end) in (gathered or _hk_gather(P, O)).items():
        if len(entry) < 10:
            continue
        r = entry * r_pct
        sig = touches(hi, lo, entry, side, r, end)
        opp = touches(hi, lo, entry, -side, r, end)
        rows.append({"rule": name, "entry": hm, "exit": ex_hm, "R_pct": r_pct * 100,
                     **profile(sig, opp, cost_rt / r_pct, half=day >= split)})
    return pd.DataFrame(rows)


def hk_stop_grid(P: dict, O: pd.DataFrame, split: str, stops=(None, 0.01, 0.02, 0.03),
                 cost_rt: float = HK_COST_RT, gathered=None) -> pd.DataFrame:
    """不设止盈、到点平仓，只改止损宽度：持仓期间最不利价格碰到止损就按止损价出。"""
    rows = []
    for (name, hm, ex_hm), (day, entry, side, hi, lo, end) in (gathered or _hk_gather(P, O)).items():
        if len(entry) < 10:
            continue
        adverse = np.where(side > 0, 1 - np.nanmin(lo, axis=1) / entry, np.nanmax(hi, axis=1) / entry - 1)
        hold = side * (end / entry - 1)
        for st in stops:
            r = (hold if st is None else np.where(adverse >= st, -st, hold)) - cost_rt
            a, b = r[day < split], r[day >= split]
            rows.append({"rule": name, "entry": hm, "exit": ex_hm, "stop": st, "n": len(r),
                         "exp_bps": r.mean() * 1e4, "win": float((r > 0).mean()),
                         "stopped": float(np.mean(adverse >= st)) if st is not None else 0.0,
                         "worst_bps": r.min() * 1e4, "adv90_bps": float(np.nanpercentile(adverse, 90)) * 1e4,
                         "first_bps": a.mean() * 1e4 if len(a) else np.nan,
                         "second_bps": b.mean() * 1e4 if len(b) else np.nan})
    return pd.DataFrame(rows)


EXIT_TIMES = ["09:31", "10:00", "10:30", "11:00", "11:59", "13:30", "14:30", "15:59"]
MAIN_RULES = ("夜里涨 >1%：08:59 做空", "09:31 合约偏离正股 >0.3%：反向做")


def hk_exit_trades(P: dict, O: pd.DataFrame, exits=EXIT_TIMES, cost_rt: float = HK_COST_RT) -> pd.DataFrame:
    """两条主规则的每笔交易：不同平仓时间的扣成本收益（列名即平仓时刻），move = 夜里涨跌或 09:31 偏离。"""
    out = []
    for s, p in P.items():
        o = O[O["symbol"] == s]
        sides = _hk_sides(p, o)
        c = p["close"]
        n859 = o.set_index("next_day")["pm_08:59"]
        basis = c["09:31"] / p["index"]["09:31"] - 1 if "09:31" in c else pd.Series(dtype=float)
        for rule, hm, move in ((MAIN_RULES[0], "08:59", n859), (MAIN_RULES[1], "09:31", basis)):
            sd = sides[rule]
            days = [d for d in sd.index if d in c.index]
            if not days or hm not in c:
                continue
            entry = c.loc[days, hm]
            t = pd.DataFrame({"symbol": s, "day": days, "rule": rule, "side": sd.loc[days].to_numpy(),
                              "move": move.reindex(days).to_numpy()})
            for T in exits:
                if T > hm and T in c:
                    t[T] = (t["side"].to_numpy() * (c.loc[days, T].to_numpy() / entry.to_numpy() - 1)) - cost_rt
            out.append(t)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def exit_curve(tr: pd.DataFrame, split: str, exits=EXIT_TIMES) -> pd.DataFrame:
    """平仓时间 → 每笔平均、胜率、前后两段，以及按交易日合并后的 t（同一天多个标的同涨同跌，只算一次）。"""
    rows = []
    for rule, g in tr.groupby("rule", sort=False):
        for T in exits:
            if T not in g or g[T].isna().all():
                continue
            x = g[T].dropna()
            day = g.loc[x.index, "day"]
            dm = x.groupby(day).mean()
            rows.append({"rule": rule, "exit": T, "n": len(x), "days": len(dm), "exp": x.mean(), "win": (x > 0).mean(),
                         "sd": x.std(ddof=1), "first": x[day < split].mean(), "second": x[day >= split].mean(),
                         "day_t": _t(dm.to_numpy())})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- 分类研究的策略（1 小时）

def hourly_paths(p, ev: np.ndarray, H: int):
    """信号在第 ev 根收盘出现，第 ev+1 根开盘成交；持有 H 根（含成交那根）。窗口不完整的丢掉。"""
    ev = ev[ev + H < len(p.c)]
    idx = (ev + 1)[:, None] + np.arange(H)[None, :]
    return ev, p.o[ev + 1], p.h[idx], p.l[idx], p.c[ev + H]


def class_study(res_dir: Path, data_dir: Path, interval: str = "1h", horizon_h: int = 72,
                r_atr: float = 4.0, cost: float = 0.0007, groups: list[str] | None = None,
                holds=(24, 72, 168)) -> pd.DataFrame:
    """用分类研究（classlab）滚动样本外每段选出的配置重新生成开仓点，只看样本外那段的开仓。
    1R = r_atr × 开仓前 1 小时 ATR(14)；cost 为单边成本；holds：另看持有这些小时后停在哪。"""
    from . import backtest as bt
    from .classlab import groups_for
    from .config import load_symbols
    from .data import load_frame, paths
    from .regime import FILTERS, regimes
    from .strategies import STRATEGIES
    folds = pd.read_csv(Path(res_dir) / "class_folds.csv")
    folds = folds[(folds["strategy"] != "AUTO") & folds["params"].notna()]
    meta = json.loads((Path(res_dir) / "class_best.json").read_text())
    symbols = [s for s in load_symbols(None) if paths(Path(data_dir), s, interval)["klines"].exists()]
    rows = []
    for group, syms in groups_for(symbols).items():
        g = folds[folds["group"] == group]
        if not len(g) or (groups and group not in groups):
            continue
        frames = {}
        for s in syms:
            f = load_frame(s, interval, Path(data_dir))
            if len(f) >= 500:
                frames[s] = f
        if not frames:
            continue
        # 与 classlab.run_class 相同的切段（初始 40% 只用来选参数，之后 3 段）
        t0 = min(f.index[0] for f in frames.values())
        t1 = max(f.index[-1] for f in frames.values())
        end = pd.Timestamp(meta.get(group, {}).get("_meta", {}).get("end", str(t1)[:10]), tz="UTC") + pd.Timedelta(days=1)
        t1 = min(t1, end)
        cuts = [t0 + (t1 - t0) * (0.4 + 0.6 * k / 3) for k in range(4)]
        preps = {s: (f, bt.Prepared.from_frame(f), regimes(f).to_numpy()) for s, f in frames.items()}
        H = max(1, int(round(horizon_h / float(next(iter(frames.values())).attrs.get("bar_hours", 1.0)))))
        for strat, gs in g.groupby("strategy"):
            st = STRATEGIES.get(strat)
            if st is None:
                continue
            acc = []
            for row in gs.itertuples():
                params = json.loads(row.params)
                lo_t, hi_t = cuts[int(row.fold) - 1], cuts[int(row.fold)]
                allowed = FILTERS.get(row.filter)
                for s, (f, p, reg) in preps.items():
                    if not st.available(f):
                        continue
                    sg = np.asarray(st.signal(f, params))
                    prev = np.concatenate([[0], sg[:-1]])
                    ev = np.flatnonzero((sg != 0) & (sg != prev))
                    ev = ev[ev + 1 < len(sg)]
                    if allowed is not None:
                        ev = ev[np.isin(reg[ev], allowed)]
                    et = f.index[ev + 1]
                    ev = ev[(et >= lo_t) & (et < hi_t)]
                    ev, entry, hi, lo, endp = hourly_paths(p, ev, H)
                    r = r_atr * p.atr[ev]
                    ok = np.isfinite(r) & (r > 0)
                    xs = np.column_stack([np.where(ev + h < len(p.c), p.c[np.minimum(ev + h, len(p.c) - 1)], np.nan)
                                          for h in holds]) if len(ev) else np.empty((0, len(holds)))
                    if ok.any():
                        acc.append((sg[ev][ok], entry[ok], hi[ok], lo[ok], endp[ok], r[ok], f.index[ev + 1][ok], xs[ok]))
            if not acc:
                continue
            side = np.concatenate([a[0] for a in acc]).astype(float)
            entry = np.concatenate([a[1] for a in acc])
            hi, lo = np.vstack([a[2] for a in acc]), np.vstack([a[3] for a in acc])
            endp, r = np.concatenate([a[4] for a in acc]), np.concatenate([a[5] for a in acc])
            when = np.concatenate([np.asarray(a[6]) for a in acc])
            xs = np.vstack([a[7] for a in acc])
            if len(side) < 20:
                continue
            sig = touches(hi, lo, entry, side, r, endp)
            opp = touches(hi, lo, entry, -side, r, endp)
            split = np.sort(when)[len(when) // 2]
            cost_r = 2 * cost * entry / r
            ends = {h: side * (xs[:, i] - entry) / r for i, h in enumerate(holds)}
            rows.append({"group": group, "strategy": strat, "label": st.label, "R_atr": r_atr,
                         "horizon_h": horizon_h, "R_pct_med": float(np.median(r / entry) * 100),
                         **profile(sig, opp, cost_r, half=when >= split), **path_profile(sig, opp, cost_r, ends)})
    return pd.DataFrame(rows)
