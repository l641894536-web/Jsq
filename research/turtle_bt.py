"""海龟式日线趋势组合（按币安上能做的品种），2021-11 → 2026-10，扣手续费和资金费。
品种：黄金、白银、铂金、钯金、铜、天然气（Dukascopy 现货/CFD 小时线合成日线），7个主流币（币安），纳指/标普/罗素ETF（Yahoo日线，币安有 QQQ/SPY/IWM 合约）。
规则（Curtis Faith《海龟交易法则》原版，按收盘价执行，止损按盘中价）：
  N = 20日真实波幅的指数平均；1个单位 = 账户的 1% ÷ (N/价格)，即价格走 1N 盈亏 1%；止损 = 最后一次加仓价 ∓ 2N
  系统1：收盘突破20日高/低进场，跌破10日低/高离场；系统2：55日 / 20日
  每走 0.5N 加1个单位，单个品种最多4个单位；同一组（贵金属 / 币 / 股指）最多6个单位；同方向合计最多12个单位
费用：每次成交 0.05%；多单资金费 0.03%/天（按自然日）；空单不收不付（保守）。
用法：python3 turtle_bt.py"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np

START, MID, END = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-01"), pd.Timestamp("2026-10-31")
FEE, FUND = 0.0005, 0.0003
GROUP = {"XAU": "metal", "XAG": "metal", "XPT": "metal", "XPD": "metal", "COPPER": "copper", "NATGAS": "gas",
         "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "BNB": "crypto", "XRP": "crypto", "DOGE": "crypto", "ADA": "crypto",
         "QQQ": "equity", "SPY": "equity", "IWM": "equity"}
NAME = {"XAU": "黄金", "XAG": "白银", "XPT": "铂金", "XPD": "钯金", "COPPER": "铜", "NATGAS": "天然气", "BTC": "比特币", "ETH": "以太坊",
        "SOL": "SOL", "BNB": "BNB", "XRP": "XRP", "DOGE": "DOGE", "ADA": "ADA", "QQQ": "纳指(QQQ)", "SPY": "标普(SPY)", "IWM": "罗素2000(IWM)"}


def build():
    D = {}
    dk = load.dukascopy(["XAUUSD", "XAGUSD", "XPTCMDUSD", "XPDCMDUSD", "COPPERCMDUSD", "GASCMDUSD"], start="2020-01")
    for sym, k in [("XAUUSD", "XAU"), ("XAGUSD", "XAG"), ("XPTCMDUSD", "XPT"), ("XPDCMDUSD", "XPD"), ("COPPERCMDUSD", "COPPER"), ("GASCMDUSD", "NATGAS")]:
        g = dk[dk.symbol == sym].copy()
        g["day"] = (g.ts + pd.Timedelta(hours=3)).dt.tz_localize(None).dt.normalize()     # 纽约17点换日
        d = g.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        D[k] = d[d.index.dayofweek < 5]
    cr = load.binance("1h", [s + "USDT" for s in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]], start="2020-01-01")
    for sym, g in cr.groupby("symbol"):
        g = g.assign(day=g.ts.dt.tz_localize(None).dt.normalize())
        D[sym.replace("USDT", "")] = g.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    us = load.us_daily(["QQQ", "SPY", "IWM"]); us["date"] = pd.to_datetime(us.date)
    for t, g in us.groupby("ticker"):
        D[t] = g.set_index("date")[["open", "high", "low", "close"]].sort_index()
    out = {}
    for k, d in D.items():
        d = d.sort_index().astype(float)
        pc = d.close.shift(1)
        tr = np.maximum(d.high - d.low, np.maximum((d.high - pc).abs(), (d.low - pc).abs()))
        d["N"] = tr.ewm(alpha=1 / 20, adjust=False).mean()
        d["ma200"] = d.close.rolling(200).mean()
        for L in (10, 20, 55):
            d[f"hi{L}"] = d.high.rolling(L).max().shift(1); d[f"lo{L}"] = d.low.rolling(L).min().shift(1)
        out[k] = d[d.index <= END]
    return out


def run(D, entryL=20, exitL=10, mode="both", risk=0.01, max_units=4, group_cap=6, dir_cap=12, rand=None, syms=None, p_rand=None, dd_cut=False):
    """mode: both / long / regime（多单只在自身200日线上方、空单只在下方）/ regime_long
    rand：随机进场对照（np.random.Generator）——每天以和真信号相同的频率随机开仓，方向随机（受 mode 限制），其余规则完全一样"""
    syms = syms or list(D)
    days = sorted(set().union(*[D[s].index[(D[s].index >= START) & (D[s].index <= END)] for s in syms]))
    eq, cash = 1.0, 1.0
    peak = 1.0
    pos = {}            # s -> dict(dir, units=[(qty, px)], stop, last, N, entry_day, regime, pnl)
    trades, curve = [], []
    last_px = {}
    p_sig = {s: p_rand or (0.04 if entryL == 20 else 0.02) for s in syms}
    prev_day = None
    for day in days:
        gap = (day - prev_day).days if prev_day is not None else 1
        prev_day = day
        # 1) 先处理已有仓位：盘中止损 / 离场通道（今天的K线）
        for s in list(pos):
            d = D[s]
            if day not in d.index: continue
            r = d.loc[day]; p = pos[s]; dr = p["dir"]
            qty = sum(q for q, _ in p["units"])
            # 资金费（多单）
            if dr == 1:
                f = FUND * gap * qty * last_px.get(s, r.open); cash -= f; p["pnl"] -= f
            ext = r[f"lo{exitL}"] if dr == 1 else r[f"hi{exitL}"]
            hit_stop = (r.low <= p["stop"]) if dr == 1 else (r.high >= p["stop"])
            hit_exit = (r.low <= ext) if dr == 1 else (r.high >= ext)
            if hit_stop or hit_exit:
                lvl = p["stop"] if hit_stop else ext
                if hit_stop and hit_exit: lvl = max(p["stop"], ext) if dr == 1 else min(p["stop"], ext)
                px = min(r.open, lvl) if dr == 1 else max(r.open, lvl)
                g = sum(q * (px - e) * dr for q, e in p["units"]) - FEE * qty * px
                cash += g; p["pnl"] += g
                trades.append(dict(sym=s, dir=dr, entry=p["entry_day"], exit=day, units=len(p["units"]), pnl=p["pnl"], r0=p["r0"],
                                   regime=p["regime"], why="止损" if (hit_stop and lvl == p["stop"]) else "离场通道"))
                del pos[s]
        # 2) 收盘：加仓、新开仓
        for s in syms:
            d = D[s]
            if day not in d.index: continue
            r = d.loc[day]; last_px[s] = r.close
            if not np.isfinite(r.N) or not np.isfinite(r[f"hi{entryL}"]): continue
            N = r.N; mult = 0.8 ** int(max(0.0, 1 - eq / peak) / 0.10) if dd_cut else 1.0; unit_qty = risk * eq * mult / N
            gu = lambda gname: sum(len(pos[x]["units"]) for x in pos if GROUP[x] == gname)
            du = lambda dd: sum(len(pos[x]["units"]) for x in pos if pos[x]["dir"] == dd)
            if s in pos:
                p = pos[s]; dr = p["dir"]
                while len(p["units"]) < max_units and dr * (r.close - (p["last"] + dr * 0.5 * p["N"])) >= 0 and gu(GROUP[s]) < group_cap and du(dr) < dir_cap:
                    px = r.close; p["units"].append((unit_qty, px)); p["last"] = px; p["stop"] = px - dr * 2 * N
                    c = FEE * unit_qty * px; cash -= c; p["pnl"] -= c
                    if dr * (r.close - (p["last"] + dr * 0.5 * p["N"])) < 0: break
                continue
            up = r.close > r[f"hi{entryL}"]; dn = r.close < r[f"lo{entryL}"]
            if rand is not None:
                if rand.random() >= p_sig[s]: continue
                up, dn = (True, False) if rand.random() < 0.5 else (False, True)
            bull = bool(np.isfinite(r.ma200) and r.close > r.ma200)
            if mode in ("long", "regime_long"): dn = False
            if mode in ("regime", "regime_long"):
                if up and not bull: up = False
                if dn and bull: dn = False
            if mode == "long" and rand is not None: up, dn = True, False
            for dr, ok in ((1, up), (-1, dn)):
                if not ok or gu(GROUP[s]) >= group_cap or du(dr) >= dir_cap: continue
                px = r.close
                pos[s] = dict(dir=dr, units=[(unit_qty, px)], stop=px - dr * 2 * N, last=px, N=N, entry_day=day,
                              regime="牛" if bull else "熊", pnl=-FEE * unit_qty * px, r0=2 * N * unit_qty)
                cash -= FEE * unit_qty * px
                break
        # 3) 按收盘记账
        unreal = sum(sum(q * (last_px[s] - e) * pos[s]["dir"] for q, e in pos[s]["units"]) for s in pos if s in last_px)
        eq = cash + unreal
        peak = max(peak, eq)
        curve.append((day, eq))
        if eq <= 0.05: break
    C = pd.Series(dict(curve)); T = pd.DataFrame(trades)
    return C, T


def stats(C):
    if len(C) < 30: return dict(cagr=np.nan, mdd=np.nan, sharpe=np.nan)
    yrs = (C.index[-1] - C.index[0]).days / 365.25
    cagr = (C.iloc[-1] / C.iloc[0]) ** (1 / yrs) - 1 if C.iloc[-1] > 0 else -1
    dd = (C / C.cummax() - 1).min()
    r = C.pct_change().dropna(); sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    return dict(cagr=cagr, mdd=dd, sharpe=sh)


def halves(C):
    a = C[C.index < MID]; b = C[C.index >= MID]
    return stats(a)["cagr"], stats(b / b.iloc[0] if len(b) else b)["cagr"]


if __name__ == "__main__":
    D = build()
    pd.set_option("display.width", 220)
    rows = []
    res = {}
    for sysname, (eL, xL) in {"系统1(20/10)": (20, 10), "系统2(55/20)": (55, 20)}.items():
        for mode, mname in {"both": "多空都做", "long": "只做多", "regime": "200日线上做多/下做空", "regime_long": "只在200日线上做多"}.items():
            C, T = run(D, eL, xL, mode)
            s = stats(C); h1, h2 = halves(C)
            yr = C.resample("YE").last().pct_change(); yr.iloc[0] = C.resample("YE").last().iloc[0] / C.iloc[0] - 1
            rows.append(dict(系统=sysname, 方向=mname, 年化=f"{s['cagr']*100:+.1f}%", 最大回撤=f"{s['mdd']*100:.1f}%", 夏普=round(s["sharpe"], 2),
                             前段年化=f"{h1*100:+.1f}%", 后段年化=f"{h2*100:+.1f}%", 笔数=len(T), 赚的比例=f"{(T.pnl > 0).mean()*100:.0f}%" if len(T) else "",
                             **{str(k.year): f"{v*100:+.0f}%" for k, v in yr.items()}))
            res[(sysname, mode)] = (C, T)
    R = pd.DataFrame(rows); print(R.to_string(index=False))
    import pickle; pickle.dump((res, {k: v for k, v in D.items()}), open("/home/claude/bt/turtle_res.pkl", "wb"))
