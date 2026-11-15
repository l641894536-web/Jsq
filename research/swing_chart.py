"""行情结构图：用真实日线（前复权，最新价=实际价）找摆动高低点，只描述结构，不是买卖规则。
转折幅度 thr（逐日、只用当天之前的数据）：
  thr[t] = 5 × 之前250个交易日（到 t-1 为止，至少120天）日收益率的标准差，四舍五入到1%，限制在12%~22%。
  也就是说，判断某一天算不算"转折"，用的是那天之前一年的波动，不用之后的数据。
高低点（因果）：从一个高点（期间最高价）起，某天收盘 ≤ 高点×(1−thr[当天]) → 这个高点"已确认"，确认日=那天；
  低点对称（收盘 ≥ 低点×(1+thr[当天])）。最后一个还没被反向走够幅度的极值 = "候选"，会被新的价格取代。
三种价位（名字分开，含义不同）：
  算法确认价   候选点变成"已确认"所需的收盘价（候选低点×(1+thr) 或 候选高点×(1−thr)）。这是本算法的口径，不是市场上的支撑/压力。
  局部结构参考价 最近的局部低点和局部高点（候选点，或刚确认的那个点），用来看"低点有没有抬高、高点有没有被越过"。
  中期压力位   最近一个已确认的高点（下降结构里就是最近那个更低的高点）；收盘站上它，"高点降低"的序列才被打破。
用法：python3 research/swing_chart.py [输出目录]   （数据：MARKET_DATA 指向 data 分支的检出）"""
import os, sys, json
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else "."
import numpy as np, pandas as pd
from market_data import load
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"); plt.rcParams["font.family"] = fm.FontProperties(fname="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc").get_name()
plt.rcParams["axes.unicode_minus"] = False

NAMES = {"sz.002463": "沪电股份", "sh.601138": "工业富联", "sh.512760": "国泰半导体ETF", "sh.601899": "紫金矿业", "sz.000636": "风华高科", "sz.000977": "浪潮信息"}

def get(code):
    if code == "sh.512760":
        u = load.us_daily(["512760.SS"], start="2022-06-01").sort_values("date").set_index("date")[["open", "high", "low", "close"]].astype(float)
        c = u.close.to_numpy().copy(); f = np.ones(len(c))
        for t in range(1, len(c)):                       # 拆分：单日跌超30% → 之前的价格按整数比例折算
            q = c[t] / c[t - 1]
            if q < 0.7: k = round(1 / q); c[:t] /= k; f[:t] /= k
        for col in u: u[col] = u[col].to_numpy() * f
        bad = (u.high / u.low > 1.25) | (u.close.pct_change().abs() > 0.22)
        return u[~bad]
    x = load.a_share(start="2022-06-01", codes=[code], adjust="qfq").sort_values("date").set_index("date")
    return x[x.tradestatus.astype(float) == 1][["open", "high", "low", "close"]].astype(float)

def thr_series(x):
    r = x.close.pct_change()
    sd = r.rolling(250, min_periods=120).std().shift(1)          # 只用到前一天
    return (5 * sd).round(2).clip(0.12, 0.22)

def pivots(x, TH):
    H, L, C, D = x.high.to_numpy(), x.low.to_numpy(), x.close.to_numpy(), x.index
    th = TH.to_numpy(); t0 = int(np.argmax(np.isfinite(th)))
    piv = []; mode = None; hi = lo = t0
    for t in range(t0 + 1, len(C)):
        if mode is None:
            if H[t] > H[hi]: hi = t
            if L[t] < L[lo]: lo = t
            if C[t] <= H[hi] * (1 - th[t]): piv.append(("H", hi, t, th[t])); mode = "dn"; lo = hi + int(np.argmin(L[hi:t + 1]))
            elif C[t] >= L[lo] * (1 + th[t]): piv.append(("L", lo, t, th[t])); mode = "up"; hi = lo + int(np.argmax(H[lo:t + 1]))
        elif mode == "up":
            if H[t] > H[hi]: hi = t
            if C[t] <= H[hi] * (1 - th[t]): piv.append(("H", hi, t, th[t])); mode = "dn"; lo = hi + int(np.argmin(L[hi:t + 1]))
        else:
            if L[t] < L[lo]: lo = t
            if C[t] >= L[lo] * (1 + th[t]): piv.append(("L", lo, t, th[t])); mode = "up"; hi = lo + int(np.argmax(H[lo:t + 1]))
    cand = ("H", hi) if mode == "up" else ("L", lo)
    return piv, cand, mode

OUT = {}
for code, name in NAMES.items():
    x = get(code); TH = thr_series(x); thr = float(TH.iloc[-1])
    piv, cand, mode = pivots(x, TH); D = x.index; ma60 = x.close.rolling(60).mean()
    fp = lambda v: f"{v:.3f}" if v < 5 else f"{v:.2f}"
    px = lambda k, i: x.high.iloc[i] if k == "H" else x.low.iloc[i]
    Hs = [(i, c) for k, i, c, _ in piv if k == "H"]; Ls = [(i, c) for k, i, c, _ in piv if k == "L"]
    info = dict(name=name, thr=thr, thr_range=[float(TH[x.index >= "2025-06-01"].min()), float(TH[x.index >= "2025-06-01"].max())], last=str(D[-1].date()), close=x.close.iloc[-1], ma60=float(ma60.iloc[-1]), mode=mode,
                highs=[(str(D[i].date()), float(x.high.iloc[i]), str(D[c].date())) for i, c in Hs[-3:]],
                lows=[(str(D[i].date()), float(x.low.iloc[i]), str(D[c].date())) for i, c in Ls[-3:]],
                cand=(cand[0], str(D[cand[1]].date()), float(px(*cand))))
    OUT[code] = info; print(json.dumps(info, ensure_ascii=False))
    # ---- 图：只画最近（包含最后4个已确认点之前40根）
    keep = sorted(piv[-5:], key=lambda z: z[1]); i0 = max(0, min(z[1] for z in keep) - 40) if keep else max(0, len(x) - 300)
    xs = np.arange(len(x))[i0:]; v = x.iloc[i0:]
    fig, ax = plt.subplots(figsize=(7.2, 5.4), dpi=150)
    ax.vlines(xs, v.low, v.high, color="#b9bec7", lw=0.8, zorder=1)
    ax.plot(xs, v.close, color="#2b3440", lw=1.3, zorder=2, label="收盘价")
    ax.plot(xs, ma60.iloc[i0:], color="#8a6fb3", lw=1.0, ls="--", zorder=2, label="60日线")
    prev = {"H": -99, "L": -99}; bump = {"H": 0, "L": 0}
    for k, i, c, th_ in piv:
        if i < i0: continue
        y = px(k, i); up = k == "H"
        bump[k] = (0 if bump[k] else 38) if i - prev[k] < 22 else 0; prev[k] = i
        ax.scatter([i], [y], marker="v" if up else "^", s=90, color="#2b3440", edgecolor="white", lw=1.2, zorder=4)
        ax.annotate(f"{'高点' if up else '低点'} {fp(y)}\n{D[i]:%y-%m-%d}\n({D[c]:%m-%d}确认,{th_:.0%})", (i, y), xytext=(bump[k], 14 if up else -14), textcoords="offset points",
                    ha="center", va="bottom" if up else "top", fontsize=7.5, color="#2b3440")
    k, i = cand; y = px(k, i); up = k == "H"
    ax.scatter([i], [y], marker="v" if up else "^", s=90, facecolor="white", edgecolor="#2b3440", lw=1.6, zorder=4)
    ax.annotate(f"候选{'高点' if up else '低点'} {fp(y)}\n{D[i]:%y-%m-%d}（未确认）", (i, y), xytext=(0, 14 if up else -14), textcoords="offset points",
                ha="center", va="bottom" if up else "top", fontsize=7.5, color="#2b3440")
    # 三种价位
    lastH = Hs[-1] if Hs else None; lastL = Ls[-1] if Ls else None
    BLUE, RED, GREY = "#3f7fbf", "#c0504d", "#7a8088"
    levels = []
    if lastH: levels.append((x.high.iloc[lastH[0]], f"中期压力位\n{fp(x.high.iloc[lastH[0]])}", BLUE, "mid"))
    if mode == "dn":
        cl = x.low.iloc[cand[1]]
        levels.append((cl * (1 + thr), f"算法确认价\n{fp(cl * (1 + thr))}", GREY, "algo"))
        levels.append((cl, f"局部参考价(候选低)\n{fp(cl)}", RED, "local_low"))
    else:
        ch = x.high.iloc[cand[1]]
        levels.append((ch, f"局部参考价(候选高)\n{fp(ch)}", BLUE, "local_high"))
        levels.append((ch * (1 - thr), f"算法确认价\n{fp(ch * (1 - thr))}", GREY, "algo"))
        if lastL: levels.append((x.low.iloc[lastL[0]], f"局部参考价(前低)\n{fp(x.low.iloc[lastL[0]])}", RED, "local_low"))
    OUT[code]["levels"] = {k: float(a) for a, _, _, k in levels}
    levels = [(a, b_, c_) for a, b_, c_, _ in levels]
    pad = max(30, int(len(xs) * 0.2))
    yr = v.high.max() - v.low.min(); ys = sorted(a for a, _, _ in levels)
    def va_of(yv):
        near_up = any(0 < o - yv < 0.07 * yr for o in ys); near_dn = any(0 < yv - o < 0.07 * yr for o in ys)
        return "top" if near_up and not near_dn else "bottom" if near_dn and not near_up else "center"
    for yv, txt, col in levels:
        ax.axhline(yv, color=col, lw=0.9, ls=":", zorder=1); ax.text(xs[-1] + pad * 0.98, yv, txt, fontsize=7.5, color="#2b3440", va=va_of(yv), ha="right", linespacing=1.0, bbox=dict(fc="white", ec=col, lw=0.6, pad=1.5))
    tk = [i for i in xs if D[i].day <= 3 and (i == xs[0] or D[i].month != D[i - 1].month)][::2]
    ax.set_xticks(tk); ax.set_xticklabels([f"{D[i]:%y-%m}" for i in tk], fontsize=8); ax.tick_params(axis="y", labelsize=8)
    ax.set_xlim(xs[0] - 2, xs[-1] + pad); ax.margins(y=0.16)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#eceef1", lw=0.6); None
    ax.set_title(f"{name}  {D[-1]:%Y-%m-%d} 收盘 {fp(x.close.iloc[-1])}   当前转折幅度 {thr:.0%}\n实线=收盘 灰竖线=当日高低 虚线=60日线   ▼高点 ▲低点：实心=已确认 空心=候选", fontsize=8.5, loc="left")
    fig.tight_layout(); fig.savefig(os.path.join(OUTDIR, f"{code.replace('.', '')}.png")); plt.close(fig)
json.dump(OUT, open(os.path.join(OUTDIR, "out.json"), "w"), ensure_ascii=False, indent=1)
