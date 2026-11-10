"""夜间止损：股票合约24小时交易，回测只看美股交易时段。同一批突破信号（交易时段小时线，出场F），比较两种挂止损的办法：
  A 只在美股交易时段有效（回测口径；夜里不挂止损，开盘跳空就按开盘价走）
  B 24小时都挂着（夜里、周末价格碰到就走）
数据：币安股票合约小时线（2026-06 起约5个月），全部有数据的股票合约都算（看的是执行差别，不是哪只能做）。样本只有5个月，结论可靠程度低。
用法：python3 night_stop_bt.py"""
import sys, os, json
sys.path.insert(0, "/home/claude/jsq"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
COST, BUF, L, BPD = 0.001, 0.001, 7, 7
ema = lambda s, n: s.ewm(span=n, adjust=False).mean()

def run(g, mode24):
    g = g.sort_values("ts").reset_index(drop=True)
    ny = g.ts.dt.tz_convert("America/New_York"); ses = ((ny.dt.dayofweek < 5) & (ny.dt.hour >= 9) & (ny.dt.hour <= 15)).to_numpy()
    S = g[ses].reset_index(drop=True); pos = np.flatnonzero(ses)           # S 的第k根在 g 里的位置
    if len(S) < 150: return []
    c_ = S.close; up = ema(c_, 20) > ema(c_, 50)
    CU = (up & ~up.shift(1, fill_value=False)).to_numpy(); CD = (~up & up.shift(1, fill_value=False)).to_numpy()
    hi, lo = S.high.rolling(L).max(), S.low.rolling(L).min()
    LS = (up & (c_ > hi.shift(1)) & (c_ > c_.shift(L))).fillna(False).to_numpy(); SS = (~up & (c_ < lo.shift(1)) & (c_ < c_.shift(L))).fillna(False).to_numpy()
    LO, HI, LO3, HI3 = lo.to_numpy(), hi.to_numpy(), S.low.rolling(3 * L).min().to_numpy(), S.high.rolling(3 * L).max().to_numpy()
    o, h, l, c = (S[k].to_numpy(float) for k in ["open", "high", "low", "close"]); go, gh, gl = (g[k].to_numpy(float) for k in ["open", "high", "low"])
    out, i, n = [], 60, len(S)
    while i < n - 1:
        side = 1 if LS[i] else (-1 if SS[i] else 0)
        if side == 0: i += 1; continue
        entry = c[i]; stop = LO[i] * (1 - BUF) if side == 1 else HI[i] * (1 + BUF); R = (entry - stop) * side
        if not (0.004 * entry <= R <= 0.08 * entry): i += 1; continue
        armed, mfe, j, px, why = False, 0.0, i + 1, None, None
        while j < n:
            if mode24:                                   # 先看上一根交易时段线收盘到这一根开盘之间的盘外小时线
                for b in range(pos[j - 1] + 1, pos[j]):
                    adv = gl[b] if side == 1 else gh[b]
                    if (adv - stop) * side <= 0: px = stop if (go[b] - stop) * side > 0 else go[b]; why = "night"; break
                if px is not None: break
            adv, fav = (l[j], h[j]) if side == 1 else (h[j], l[j])
            if (adv - stop) * side <= 0: px = stop if (o[j] - stop) * side > 0 else o[j]; why = "stop"; break
            mfe = max(mfe, (fav - entry) * side / R)
            if mfe >= 1: armed = True
            if armed:
                tr = LO3[j] * (1 - BUF) if side == 1 else HI3[j] * (1 + BUF); new = max(entry, tr) if side == 1 else min(entry, tr); stop = max(stop, new) if side == 1 else min(stop, new)
            if (CD[j] if side == 1 else CU[j]) or (j - i) >= 10 * BPD or j == n - 1: px = c[j]; why = "exit"; break
            j += 1
        r = (px - entry) * side / R - COST * entry / R
        out.append(dict(ts=S.ts[i], side=side, r=r, u=r * R / entry * 500, why=why, gapopen=(why == "stop" and (o[j] - stop) * side <= 0)))
        i = j + 1
    return out

st = json.load(open("/home/claude/market-data/status.json"))["stages"]["binance"]["stock_perps"]
H = load.binance("1h", st, start="2026-05-01")
A, B = [], []
for s, g in H.groupby("symbol"):
    a, b = run(g, False), run(g, True)
    A += [dict(x, sym=s) for x in a]; B += [dict(x, sym=s) for x in b]
A, B = pd.DataFrame(A), pd.DataFrame(B)
def line(nm, x): print(f"{nm:<26} {len(x):5d}笔  赚的 {(x.r > 0).mean()*100:.0f}%  平均每次 {x.u.mean():+.2f}U  合计 {x.u.sum():+.0f}U  夜里被打 {(x.why == 'night').mean()*100:.0f}%  开盘跳空过止损 {x.gapopen.mean()*100:.0f}%")
print("股票合约数", H.symbol.nunique(), "数据", H.ts.min().date(), "~", H.ts.max().date())
for side, nm in ((1, "做多"), (-1, "做空"), (0, "全部")):
    a = A if side == 0 else A[A.side == side]; b = B if side == 0 else B[B.side == side]
    line(f"{nm} A 只在交易时段挂止损", a); line(f"{nm} B 24小时挂止损", b)
m3 = ["AMDUSDT", "MUUSDT", "DELLUSDT"]
line("AMD/美光/戴尔 A", A[A.sym.isin(m3)]); line("AMD/美光/戴尔 B", B[B.sym.isin(m3)])
# 同一笔进场（两种做法进场时间相同的）逐笔比较
M = A.merge(B, on=["sym", "ts", "side"], suffixes=("_a", "_b"))
d = M[M.why_b == "night"]
print(f"两种做法同时进场的 {len(M)} 笔里，B 在夜里被打掉 {len(d)} 笔（{len(d)/len(M)*100:.0f}%）；这些单子 A 的结果平均 {d.u_a.mean():+.2f}U，B 平均 {d.u_b.mean():+.2f}U；其中 A 最后是赚的 {(d.u_a > 0).mean()*100:.0f}%")
gp = A[A.gapopen]; print(f"A 做法里开盘直接跳过止损的 {len(gp)} 笔，平均亏 {gp.r.mean():.2f} 份止损（正常止损是 −1 份左右）")
