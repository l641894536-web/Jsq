"""冻结规则的历史表现与样本外跟踪（规则见 docs/indicators_rules.md）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as I
from .panel import Panel
from .stats import block_ci
from .xsec import backtest_rows, xs_rank

FREEZE = pd.Timestamp("2026-09-30")
H = 20
HEAT = ["ret_20", "rsi_14", "amt_ratio_5_20", "max_ret_20"]
PERIODS = [("发现集", "2012-01-01", "2017-12-31"), ("验证集", "2018-01-01", "2022-12-31"),
           ("测试集", "2023-01-01", "2026-09-29"), ("样本外", "2026-09-30", "2100-01-01")]
RULES = {"I1": "做多成交额最低 10%", "I2": "回避 20 日内涨停", "I3": "剔除最热 10%（候选）"}


def heat_score(P: Panel, E: np.ndarray) -> np.ndarray:
    parts = []
    for name in HEAT:
        u, _ = xs_rank(np.where(E, I.compute(name, P), np.nan))
        parts.append(u + 0.5)
    st = np.stack(parts)
    cnt = np.isfinite(st).sum(0)
    with np.errstate(all="ignore"):
        h = np.nanmean(st, axis=0)
    h[cnt < 3] = np.nan
    return h


def rule_series(P: Panel, cfg: dict) -> pd.DataFrame:
    u, t = cfg["universe"], cfg["trade"]
    tol, md = u["limit_tol"], t["max_sell_delay"]
    P.cache["tol"] = tol
    E = P.eligible(u["min_listed_days"], tol)
    traded = np.isfinite(P.C) & (np.nan_to_num(P.V) > 0)
    nxt = np.zeros_like(P.in_univ)
    nxt[:-1] = np.isfinite(P.O[1:])
    E_pre = P.in_univ & (P.age >= u["min_listed_days"]) & traded & nxt
    oun = np.zeros_like(P.in_univ)
    oun[:-1] = P.limit_hits(tol)["open_up"][1:]
    R = P.trade_return(H, md, tol)
    _, dl = P.exit_table(md, tol)
    delayed = np.zeros_like(dl)
    delayed[: P.n - 1 - H] = dl[1 + H:]
    sd = {"I1": -I.compute("log_amount_20", P), "I2": -I.compute("limit_up_20", P), "I3": -heat_score(P, E)}
    q = {"I1": 0.10, "I2": 0.10, "I3": 0.90}
    valid = np.zeros(P.n, dtype=bool)
    valid[: P.n - 1 - H] = True
    out = {}
    for k, s in sd.items():
        bt = backtest_rows(s, False, E, E_pre, oun, R, delayed, H, q[k])
        net = bt["port"] - t["roundtrip_cost"] * np.nan_to_num(bt["turnover"], nan=1.0) - bt["bench"]
        out[f"{k}_net"] = np.where(valid, net, np.nan)
        out[f"{k}_hold"] = bt["n_hold"]
        out[f"{k}_turnover"] = bt["turnover"]
    return pd.DataFrame(out, index=P.dates)


def summarize(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    rows = []
    for k, name in RULES.items():
        for lab, a, b in PERIODS:
            x = df.loc[a:b, f"{k}_net"].to_numpy(dtype=float)
            x = x[np.isfinite(x)]
            if len(x) == 0:
                rows.append({"规则": k, "说明": name, "区间": lab, "交易日": 0})
                continue
            lo, hi = block_ci(x, 40, cfg["test"]["n_boot"], 0.10, seed=1)
            rows.append({"规则": k, "说明": name, "区间": lab, "交易日": len(x), "年化超额(净)": x.mean() * 252 / H,
                         "90%CI下限": lo * 252 / H, "90%CI上限": hi * 252 / H,
                         "平均持股数": float(np.nanmean(df.loc[a:b, f"{k}_hold"])),
                         "换手/期": float(np.nanmean(df.loc[a:b, f"{k}_turnover"]))})
    return pd.DataFrame(rows)


def verdict(sm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for k in RULES:
        o = sm[(sm["规则"] == k) & (sm["区间"] == "样本外")].iloc[0]
        hist = sm[(sm["规则"] == k) & sm["区间"].isin(["验证集", "测试集"])]
        n = int(o.get("交易日", 0) or 0)
        if n < 250:
            v = f"样本外 {n} 个交易日（<250），不下结论"
        elif o["年化超额(净)"] > 0:
            v = "维持"
        elif o["90%CI上限"] < 0:
            v = "失效"
        else:
            m = float((hist["年化超额(净)"] * hist["交易日"]).sum() / hist["交易日"].sum())
            v = "存疑" if o["90%CI下限"] <= m <= o["90%CI上限"] else "失效"
        rows.append({"规则": k, "说明": RULES[k], "判定": v})
    return pd.DataFrame(rows)
