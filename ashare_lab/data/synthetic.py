"""合成数据：只用于验证代码流程、以及检验“方法能不能找回事先埋进去的规律”。

合成数据上跑出来的任何数字都不是A股结论！
埋入的规律（真值）会返回给测试用例：
- 主线波段：上涨段加速、成交占比随超额收益升高（拥挤），顶部后回撤；
- TMT 组合的几次联合行情，成交占比可到 40%~50%；
- 顶部附近的大跌（趋势结束型）与上涨中途的大跌（机会型）；
- 行业内扩散：龙头先涨、尾部后段补涨；
- 牛/熊/震荡三种市场状态，牛市后段小票（“垃圾股”）跑赢。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import MarketData

SECTORS = [
    ("S01", "科技A", "TMT"), ("S02", "科技B", "TMT"), ("S03", "科技C", "TMT"), ("S04", "科技D", "TMT"),
    ("S05", "周期A", "周期"), ("S06", "周期B", "周期"), ("S07", "周期C", "周期"), ("S08", "周期D", "周期"),
    ("S09", "消费A", "大消费"), ("S10", "消费B", "大消费"), ("S11", "消费C", "大消费"), ("S12", "消费D", "大消费"),
    ("S13", "金融A", "大金融"), ("S14", "金融B", "大金融"), ("S15", "稳定A", "稳定"), ("S16", "稳定B", "稳定"),
]

# 预设的 TMT 联合主线：(起点, 上涨天数, 下跌天数, 超额涨幅, 回撤比例)
TMT_EPISODES = [
    ("2014-11-03", 140, 110, 0.90, 0.75),
    ("2019-01-04", 230, 150, 0.60, 0.60),
    ("2023-01-03", 90, 130, 0.55, 0.80),
    ("2025-01-02", 190, 120, 0.70, 0.50),
]


def _profile_up(length: int, total_log: float) -> np.ndarray:
    w = (np.arange(1, length + 1) / length) ** 1.5
    return w / w.sum() * total_log


def make_synthetic(seed: int = 7, start: str = "2014-01-02", end: str = "2026-06-30",
                   stocks_per_sector: int = 20, with_stocks: bool = True, null: bool = False) -> tuple[MarketData, dict]:
    """null=True：不埋任何规律（无主线、无拥挤-热度联动、无大跌、无扩散、无小票补涨），用于检验方法的误报率。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    n = len(dates)
    K = len(SECTORS)
    codes = [c for c, _, _ in SECTORS]

    # ---------------- 市场状态 ----------------
    states = []
    prev = None
    while len(states) < n:
        choices = [s for s in ("bull", "bear", "range") if s != prev]
        st = rng.choice(choices)
        states += [st] * int(rng.integers(120, 360))
        prev = st
    states = np.array(states[:n])
    mu = np.select([states == "bull", states == "bear"], [0.0012, -0.0010], 0.0)
    if null:
        mu = np.zeros(n)  # 零假设：市场也没有可预测的趋势
    sig = np.select([states == "bull", states == "bear"], [0.013, 0.017], 0.010)
    r_m = mu + sig * rng.standard_normal(n)

    # 牛市后段：小票/垃圾股补涨
    seg_id = np.cumsum(np.r_[1, states[1:] != states[:-1]])
    late_bull = np.zeros(n, dtype=bool)
    for s in np.unique(seg_id):
        idx = np.flatnonzero(seg_id == s)
        if states[idx[0]] == "bull":
            late_bull[idx[int(len(idx) * 0.65):]] = True
    junk = np.where(late_bull, 0.0015, np.where(states == "bear", -0.0008, 0.0)) + 0.004 * rng.standard_normal(n)
    if null:
        junk = 0.004 * rng.standard_normal(n)

    # ---------------- 行业主线波段 ----------------
    drift = np.zeros((n, K))
    busy = np.zeros((n, K), dtype=bool)
    episodes = []

    def plant(k: int, t0: int, up: int, down: int, gain: float, retrace: float):
        if t0 < 0 or t0 + up >= n:
            return False
        down = min(down, n - 1 - (t0 + up))
        lg = np.log1p(gain)
        drift[t0:t0 + up, k] += _profile_up(up, lg)
        if down > 0:
            drift[t0 + up:t0 + up + down, k] -= retrace * lg / down
        busy[max(0, t0 - 40):min(n, t0 + up + down + 40), k] = True
        episodes.append({"sector": codes[k], "t0": dates[t0], "peak": dates[t0 + up],
                         "bottom": dates[t0 + up + down] if down > 0 else pd.NaT,
                         "gain": gain, "up_days": up, "down_days": down})
        return True

    for d0, up, down, gain, retrace in ([] if null else TMT_EPISODES):
        t0 = int(dates.searchsorted(pd.Timestamp(d0)))
        for k in range(4):
            jitter = int(rng.integers(-5, 6))
            plant(k, t0 + jitter, up, down, gain * rng.uniform(0.85, 1.15), retrace)

    for k in range(4, 4 if null else K):
        for _ in range(int(rng.integers(1, 3))):
            for _try in range(30):
                up, down = int(rng.integers(80, 220)), int(rng.integers(60, 180))
                t0 = int(rng.integers(260, n - up - 20))
                if not busy[t0:t0 + up + down, k].any():
                    plant(k, t0, up, down, rng.uniform(0.35, 0.9), rng.uniform(0.5, 0.9))
                    break

    # 大跌：顶部附近（趋势结束型）+ 上涨中段（机会型）
    shocks = np.zeros((n, K))
    crash_truth = []
    for ep in episodes:
        k = codes.index(ep["sector"])
        tp = int(dates.get_loc(ep["peak"]))
        t0 = int(dates.get_loc(ep["t0"]))
        if rng.random() < 0.8:
            t = tp + int(rng.integers(0, 6))
            if t < n:
                shocks[t, k] += -rng.uniform(0.06, 0.10)
                crash_truth.append({"sector": ep["sector"], "date": dates[t], "type": "end"})
        if rng.random() < 0.7:
            t = t0 + int(ep["up_days"] * rng.uniform(0.45, 0.6))
            shocks[t, k] += -rng.uniform(0.055, 0.08)
            crash_truth.append({"sector": ep["sector"], "date": dates[t], "type": "dip"})

    beta = rng.uniform(0.8, 1.25, K)
    idio = rng.uniform(0.008, 0.012, K) * rng.standard_normal((n, K))
    sec_log = beta[None, :] * r_m[:, None] + idio + drift + np.log1p(shocks)
    sector_close = pd.DataFrame(1000 * np.exp(np.cumsum(sec_log, axis=0)), index=dates, columns=codes)

    # ---------------- 成交额：随热度（超额收益）上升 ----------------
    exc = sec_log - r_m[:, None]
    exc20 = pd.DataFrame(exc, index=dates).rolling(20, min_periods=1).sum().to_numpy()
    heat = np.clip(exc20, -0.3, 0.6)
    if null:
        heat = np.zeros_like(heat)
    mret60 = pd.Series(r_m).rolling(60, min_periods=1).sum().to_numpy()
    activity = np.exp(1.5 * mret60)
    size = np.array([0.07] * 4 + [0.72 / 12] * 12)
    amt = size[None, :] * activity[:, None] * np.exp(3.2 * heat + 0.15 * rng.standard_normal((n, K))) * 1e12
    sector_amount = pd.DataFrame(amt, index=dates, columns=codes)

    # ---------------- 指数 ----------------
    def idx_from(logret):
        return 1000 * np.exp(np.cumsum(logret))

    grp = {g: [i for i, (_, _, gg) in enumerate(SECTORS) if gg == g] for g in ("TMT", "周期", "大消费", "大金融", "稳定")}
    growth_lr = sec_log[:, grp["TMT"] + grp["大消费"]].mean(axis=1) + 0.002 * rng.standard_normal(n)
    value_lr = sec_log[:, grp["大金融"] + grp["周期"] + grp["稳定"]].mean(axis=1) + 0.002 * rng.standard_normal(n)
    fin_exc = (sec_log[:, grp["大金融"]].mean(axis=1) - r_m)
    index_close = pd.DataFrame({
        "000985": idx_from(r_m),
        "000300": idx_from(0.95 * r_m + 0.3 * fin_exc + 0.002 * rng.standard_normal(n)),
        "000852": idx_from(1.10 * r_m + 0.8 * junk + 0.002 * rng.standard_normal(n)),
        "399303": idx_from(1.15 * r_m + 1.0 * junk + 0.002 * rng.standard_normal(n)),
        "399370": idx_from(growth_lr),
        "399371": idx_from(value_lr),
        "000922": idx_from(sec_log[:, grp["大金融"] + grp["稳定"]].mean(axis=1) + 0.002 * rng.standard_normal(n)),
    }, index=dates)
    total = sector_amount.sum(axis=1)
    index_amount = pd.DataFrame({
        "000985": total,
        "399370": sector_amount.iloc[:, grp["TMT"] + grp["大消费"]].sum(axis=1),
        "399371": sector_amount.iloc[:, grp["大金融"] + grp["周期"] + grp["稳定"]].sum(axis=1),
    }, index=dates)

    cn10y = np.clip(3.3 + np.cumsum(0.015 * rng.standard_normal(n)), 1.5, 4.8)
    macro = pd.DataFrame({"cn10y": cn10y, "cn2y": cn10y - 0.6 + 0.1 * rng.standard_normal(n)}, index=dates)

    stocks = ind = prof = None
    stock_truth = {}
    if with_stocks:
        stocks, ind, prof, stock_truth = _make_stocks(rng, dates, sec_log, heat, episodes, codes, stocks_per_sector, null)

    groups = {g: [codes[i] for i in idx] for g, idx in grp.items()}
    data = MarketData(
        sector_close=sector_close, sector_amount=sector_amount,
        sector_names={c: nm for c, nm, _ in SECTORS},
        market_close=index_close["000985"], total_amount=total,
        index_close=index_close, index_amount=index_amount, groups=groups,
        macro=macro, stocks=stocks, stock_industry=ind, stock_profit=prof, source="synthetic",
    )
    truth = {"episodes": pd.DataFrame(episodes), "crashes": pd.DataFrame(crash_truth),
             "states": pd.Series(states, index=dates), "late_bull": pd.Series(late_bull, index=dates), **stock_truth}
    return data, truth


def _make_stocks(rng, dates, sec_log, heat, episodes, codes, m, null=False):
    n, K = sec_log.shape
    # 每个行业在每个时点所处的主线阶段：f∈[0,1) 上涨进度；-1 = 下跌段；nan = 不在波段内
    phase = np.full((n, K), np.nan)
    for ep in episodes:
        k = codes.index(ep["sector"])
        t0 = dates.get_loc(ep["t0"])
        up, down = ep["up_days"], ep["down_days"]
        phase[t0:t0 + up, k] = np.arange(up) / up
        phase[t0 + up:t0 + up + down, k] = -1.0

    rows = []
    ind_rows, prof_rows = [], []
    tiers = {}
    for k, code in enumerate(codes):
        log_mcap = rng.normal(np.log(80e8), 1.0, m)
        loss = rng.random(m) < 0.2
        pct = pd.Series(log_mcap).rank(pct=True).to_numpy()
        tier = np.where((pct > 0.8) & ~loss, "leader", np.where((pct <= 0.4) | loss, "tail", "second"))
        f = phase[:, k]
        up = np.nan_to_num(f, nan=-2.0)
        eff = {k_: np.zeros(n) for k_ in ("leader", "second", "tail")} if null else {
            "leader": np.where((up >= 0) & (up < 0.5), 0.0025, np.where(up == -1, -0.0010, 0.0)),
            "second": np.where((up >= 0.33) & (up < 0.8), 0.0015, np.where(up == -1, -0.0015, 0.0)),
            "tail": np.where((up >= 0) & (up < 0.5), -0.0010, np.where(up >= 0.66, 0.0045, np.where(up == -1, -0.0030, 0.0))),
        }
        for j in range(m):
            scode = f"{k + 1:02d}{j:04d}"
            lr = sec_log[:, k] + eff[tier[j]] + 0.02 * rng.standard_normal(n)
            close = 10 * np.exp(np.cumsum(lr))
            mcap = np.exp(log_mcap[j]) * close / close[0]
            tail_heat = 1.0 if tier[j] == "tail" else 0.0
            turnover = np.clip(1.5 * np.exp(2.0 * heat[:, k] + 0.5 * tail_heat * np.clip(np.nan_to_num(f, nan=0), 0, 1)
                                           + 0.3 * rng.standard_normal(n)), 0.05, 40)
            rows.append(pd.DataFrame({"date": dates, "code": scode, "close": close,
                                      "amount": turnover / 100 * mcap, "turnover": turnover}))
            ind_rows.append({"code": scode, "sector": code, "start_date": pd.Timestamp("2000-01-01")})
            for y in range(2013, dates[-1].year):
                prof_rows.append({"code": scode, "report_date": pd.Timestamp(f"{y}-12-31"),
                                  "ann_date": pd.Timestamp(f"{y + 1}-04-15"),
                                  "net_profit": -1e8 if loss[j] else 1e8})
            tiers[scode] = tier[j]
    stocks = pd.concat(rows, ignore_index=True)
    return stocks, pd.DataFrame(ind_rows), pd.DataFrame(prof_rows), {"stock_tiers": pd.Series(tiers)}
