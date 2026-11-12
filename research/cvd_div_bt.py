"""CVD 底背离（价格创新低、累计主动买卖差没创新低）到底有没有用？

做法（1小时线，收盘价判断，避免PAXG早年插针）：
  背离：收盘创近 N 根新低，但 CVD（累计 主动买-主动卖）没创近 N 根新低
  左侧：背离那根收盘就进
  右侧确认（帖子说的"重新站上短期阻力、CVD同步走强"）：背离后 M 根内，收盘站上前 K 根最高，且 CVD 高于背离那根 → 进
  对照：同样"创新低→站上前K根最高"，但不看 CVD（看 CVD 到底有没有多出来的东西）
止损：背离以来最低点下方 0.1%；出场和交易台一样（1R 保本→跟踪3天低点、小时线趋势反转、最多10天）。
成绩：每笔多少 R，以及 100U 开5倍 每笔赚亏多少 U（扣 0.1% 手续费）。牛熊分开（币看比特币50日线，金银看自己50日线）。
做空是镜像（价格新高、CVD 没新高）。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np, pandas as pd
from market_data import load

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]
COST, NOT = 0.001, 500.0


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def entries(df, side, N, K, M, mode):
    c, h, l = df.close.to_numpy(), df.high.to_numpy(), df.low.to_numpy()
    cvd = (2 * df.taker_buy_volume - df.volume).cumsum().to_numpy()
    cs = pd.Series(c * side); vs = pd.Series(cvd * side)
    ext = (cs < cs.shift(1).rolling(N).min()).to_numpy()                       # 多：收盘新低（空：新高）
    nodiv = (vs > vs.shift(1).rolling(N).min()).to_numpy()                    # CVD 没跟着创新低
    out, i, n = [], N + 1, len(c)
    while i < n - 1:
        if not ext[i] or (mode != "plain" and not nodiv[i]): i += 1; continue
        if mode == "left":
            st = (l[max(0, i - 3):i + 1].min() * 0.999) if side == 1 else (h[max(0, i - 3):i + 1].max() * 1.001)
            out.append((i, st)); i += 1; continue
        # 右侧确认：M 根内收盘越过前 K 根高（空：低），且 CVD 比背离那根强
        j_ok = None
        for j in range(i + 1, min(n, i + 1 + M)):
            lvl = h[j - K:j].max() if side == 1 else l[j - K:j].min()
            if side * (c[j] - lvl) > 0 and (mode == "plain" or side * (cvd[j] - cvd[i]) > 0): j_ok = j; break
            if side * (c[j] - c[i]) < 0 and ext[j]: break                    # 又创新低：这次背离作废，从新的点重来
        if j_ok is None: i += 1; continue
        st = (l[i:j_ok + 1].min() * 0.999) if side == 1 else (h[i:j_ok + 1].max() * 1.001)
        out.append((j_ok, st)); i = j_ok + 1
    return out


def sim(df, ents, side, L=24, max_bars=240):
    c, h, l, o = (df[k].to_numpy() for k in ["close", "high", "low", "open"])
    up = (ema(df.close, 20) > ema(df.close, 50)).to_numpy()
    res, busy = [], -1
    for i, st0 in ents:
        if i <= busy: continue
        E = c[i]; Rk = side * (E - st0)
        if not (0.002 * E <= Rk <= 0.08 * E): continue
        st, armed, mfe, px, j = st0, False, 0.0, None, i + 1
        while j < len(c):
            adv = l[j] if side == 1 else h[j]
            if side * (adv - st) <= 0: px = st if side * (o[j] - st) > 0 else o[j]; break
            mfe = max(mfe, side * ((h[j] if side == 1 else l[j]) - E) / Rk)
            if mfe >= 1: armed = True
            if armed:
                tr = l[max(0, j - 3 * L + 1):j + 1].min() * 0.999 if side == 1 else h[max(0, j - 3 * L + 1):j + 1].max() * 1.001
                st = max(st, E, tr) if side == 1 else min(st, E, tr)
            if (side == 1 and not up[j] and up[j - 1]) or (side == -1 and up[j] and not up[j - 1]) or j - i >= max_bars: px = c[j]; break
            j += 1
        if px is None: break                                                   # 最后还没平的不算
        r = side * (px - E) / Rk - COST * E / Rk
        res.append(dict(ts=df.ts.iloc[i], r=r, u=NOT * (side * (px - E) / E - COST))); busy = j
    return res


def regime(close_daily, n=50):
    d = close_daily.copy(); d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    return (d > d.rolling(n).mean()).shift(1)                                  # 用前一天收盘判断


def daily_close(df):
    x = df.set_index(df.ts.dt.tz_convert(None)).close.resample("1D").last().dropna(); return x


def run_group(name, frames, reg_of, start, rows):
    for side in (1, -1):
        for N in (24, 72):
            for mode in ("left", "cvd", "plain"):
                T = []
                for sym, df in frames.items():
                    df = df[df.ts >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=60)].reset_index(drop=True)
                    for t in sim(df, entries(df, side, N, 12, 24, mode), side):
                        if t["ts"] < pd.Timestamp(start, tz="UTC"): continue
                        d = t["ts"].tz_convert(None).normalize(); b = reg_of(sym).reindex([d], method="ffill").iloc[0]
                        if pd.isna(b): continue
                        T.append(dict(t, sym=sym, bull=bool(b)))
                T = pd.DataFrame(T)
                if T.empty: continue
                mid = T.ts.quantile(0.5)
                for bull in (True, False):
                    x = T[T.bull == bull]
                    if len(x) < 5: continue
                    rows.append(dict(组=name, 方向="做多" if side == 1 else "做空", 环境="牛" if bull else "熊", N=N,
                                     做法={"left": "背离就进", "cvd": "背离+站上确认", "plain": "不看CVD,新低后站上"}[mode],
                                     笔数=len(x), 胜率=round((x.r > 0).mean() * 100), 平均R=round(x.r.mean(), 3), 每笔U=round(x.u.mean(), 2),
                                     前半R=round(x[x.ts < mid].r.mean(), 3), 后半R=round(x[x.ts >= mid].r.mean(), 3)))


def main():
    rows = []
    C = load.binance("1h", COINS, start="2021-06-01")
    coins = {s: g.sort_values("ts").reset_index(drop=True) for s, g in C.groupby("symbol")}
    btc = regime(daily_close(coins["BTCUSDT"]))
    run_group("7个币(5年)", coins, lambda s: btc, "2021-11-01", rows)
    P = load.binance_spot("1h", "PAXGUSDT").sort_values("ts").reset_index(drop=True)
    pr = regime(daily_close(P))
    run_group("黄金PAXG现货(2020-26)", {"PAXGUSDT": P}, lambda s: pr, "2021-01-01", rows)
    M = load.binance("1h", ["XAUUSDT", "XAGUSDT"]); mets = {s: g.sort_values("ts").reset_index(drop=True) for s, g in M.groupby("symbol")}
    mreg = {s: regime(daily_close(g)) for s, g in mets.items()}
    run_group("金银永续(2026)", mets, lambda s: mreg[s], "2026-03-01", rows)
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(R.to_string(index=False))
    R.to_csv("/home/claude/bt/cvd_div_results.csv", index=False)


if __name__ == "__main__":
    main()
