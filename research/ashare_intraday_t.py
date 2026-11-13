"""A股科技股 盘中：高开怎么卖、低开怎么做T（5分钟线，baostock，2021-11 起为主）。
标的：用户持仓 沪电股份、工业富联、国泰半导体ETF + 同类科技股/半导体ETF（config.A_MIN_CODES）。
每只每天：开盘价 O（第一根5分钟线的开盘）、前收 pc（日线前收；ETF 用前一天最后一根收盘）、跳空 gap=O/pc-1。
高开（gap≥阈值）卖法，结果都写成"卖价比开盘价高多少"（越大越好）：
  开盘卖 / 9:45 / 10:00 / 10:30 / 11:30 / 收盘卖；跌破开盘15分钟最低价卖（没跌破收盘卖）；从盘中最高回落 1.5%/2%/3% 卖；跌破分时均价线卖；事后最高价（参考上限）
低开（gap≤−阈值）买法，结果写成"买价比开盘价低多少"（越大越好），以及做T（先买后卖，用底仓）：当天卖出价/买价−1−成本
先卖后买（高开）：开盘卖底仓，当天收盘或回落到某价买回；回不来按收盘买回（亏）。
做T成本：股票来回 0.1%（佣金+卖出印花税），ETF 0.02%。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load

NAMES = {"sz.002463": "沪电股份", "sh.601138": "工业富联", "sh.512760": "半导体ETF(国泰)", "sh.512480": "半导体ETF(国联安)", "sh.588000": "科创50ETF",
         "sz.300308": "中际旭创", "sz.300502": "新易盛", "sz.300476": "胜宏科技", "sz.300394": "天孚通信", "sz.002916": "深南电路", "sz.002475": "立讯精密",
         "sz.000063": "中兴通讯", "sh.603986": "兆易创新", "sz.002371": "北方华创", "sh.688981": "中芯国际", "sh.688256": "寒武纪", "sh.688012": "中微公司",
         "sh.688041": "海光信息", "sz.002156": "通富微电", "sh.600584": "长电科技"}
MINE = ["sz.002463", "sh.601138", "sh.512760"]
M = load.a_share_min(list(NAMES), start="2021-01-01")
print("5分钟线：", len(M), "行，", M.code.nunique(), "只，", M.date.min(), "→", M.date.max())
DLY = load.a_share(start="2020-12-01", codes=list(NAMES), adjust=None)[["date", "code", "preclose", "close", "pctChg"]]
DLY = DLY.set_index(["code", "date"])
cyc = pd.read_pickle("/home/claude/bt/_cycle_s.pkl")[["阶段", "温度"]]
US = load.us_daily(["SMH", "NVDA", "QQQ"], start="2020-12-01").pivot(index="date", columns="ticker", values="close").sort_index()
usr = US.pct_change()


def us_night(d):
    """A股日 d 开盘前能看到的最近一个美股交易日（日期 < d）的涨跌"""
    i = usr.index.searchsorted(d) - 1
    return usr.iloc[i] if i >= 0 else pd.Series(dtype=float)


rows = []
for (code, d), g in M.groupby(["code", "date"], sort=True):
    g = g.sort_values("time")
    if len(g) < 40:
        continue
    o, h, l, c = g.open.to_numpy(float), g.high.to_numpy(float), g.low.to_numpy(float), g.close.to_numpy(float)
    v = g.volume.to_numpy(float); amt = g.amount.to_numpy(float)
    hm = g.time.str.slice(8, 12).to_numpy()
    O = o[0]
    try:
        pc = float(DLY.loc[(code, d), "preclose"])
    except KeyError:
        pc = np.nan
    rows.append(dict(code=code, d=d, O=O, pc=pc, hm=hm, h=h, l=l, c=c, v=v, amt=amt))
# ETF 等没有日线前收的，用前一天最后一根收盘
by = {}
for r in rows:
    by.setdefault(r["code"], []).append(r)
for code, L in by.items():
    for i, r in enumerate(L):
        if not np.isfinite(r["pc"]) and i > 0:
            r["pc"] = L[i - 1]["c"][-1]
COST = {c: (0.0002 if c.startswith("sh.51") or c.startswith("sh.58") else 0.001) for c in NAMES}


def idx_of(hm, t):
    w = np.where(hm >= t)[0]
    return w[0] if len(w) else len(hm) - 1


feats = []
for code, L in by.items():
    vol15 = []   # 过去20天开盘15分钟成交量
    for i, r in enumerate(L):
        O, pc, hm, h, l, c, v, amt = r["O"], r["pc"], r["hm"], r["h"], r["l"], r["c"], r["v"], r["amt"]
        if not (np.isfinite(pc) and pc > 0 and O > 0):
            vol15.append(v[:3].sum()); continue
        gap = O / pc - 1
        k945, k1000, k1030, k1130 = idx_of(hm, "0945"), idx_of(hm, "1000"), idx_of(hm, "1030"), idx_of(hm, "1130")
        orh, orl = h[:3].max(), l[:3].min()
        vw = np.cumsum(amt) / np.maximum(np.cumsum(v), 1)              # 分时均价（元/股）
        f = dict(code=code, d=r["d"], gap=gap, O=O, C=c[-1], H=h.max(), Lo=l.min(),
                 t_hi=hm[int(np.argmax(h))], t_lo=hm[int(np.argmin(l))],
                 p945=c[k945], p1000=c[k1000], p1030=c[k1030], p1130=c[k1130], orh=orh, orl=orl)
        # 高开卖法：跌破开盘15分钟低点卖
        sell_or = c[-1]
        for j in range(3, len(c)):
            if c[j] < orl:
                sell_or = c[j]; break
        f["s_or"] = sell_or
        for x in (0.015, 0.02, 0.03):
            run_hi = O; out = c[-1]
            for j in range(len(c)):
                run_hi = max(run_hi, h[j])
                if c[j] <= run_hi * (1 - x):
                    out = c[j]; break
            f[f"s_tr{int(x*1000)}"] = out
        out = c[-1]
        for j in range(3, len(c)):
            if c[j] < vw[j]:
                out = c[j]; break
        f["s_vw"] = out
        # 低开买法：站上开盘15分钟高点买（没站上就收盘买）；站上分时均价线买
        buy_or = np.nan
        for j in range(3, len(c)):
            if c[j] > orh:
                buy_or = c[j]; f["k_buy_or"] = j; break
        f["b_or"] = buy_or
        buy_vw = np.nan
        for j in range(3, len(c)):
            if c[j] > vw[j] and c[j - 1] <= vw[j - 1]:
                buy_vw = c[j]; f["k_buy_vw"] = j; break
        f["b_vw"] = buy_vw
        # 做T先买后卖：10:00 买，当天收盘卖 / 冲到+2%卖
        b = c[k1000]; tgt = b * 1.02; out = c[-1]
        for j in range(k1000 + 1, len(c)):
            if h[j] >= tgt:
                out = tgt; break
        f["t_b1000_tgt2"] = out / b - 1 - COST[code]
        f["t_b1000_close"] = c[-1] / b - 1 - COST[code]
        # 先卖后买：开盘卖，回落2%买回，没回落收盘买回
        back = c[-1]
        for j in range(len(c)):
            if l[j] <= O * 0.98:
                back = O * 0.98; break
        f["t_s_open_back2"] = O / back - 1 - COST[code]
        f["t_s_open_close"] = O / c[-1] - 1 - COST[code]
        # 开盘15分钟
        f["r15"] = c[2] / O - 1
        f["vr15"] = v[:3].sum() / np.mean(vol15[-20:]) if len(vol15) >= 10 and np.mean(vol15[-20:]) > 0 else np.nan
        vol15.append(v[:3].sum())
        feats.append(f)
X = pd.DataFrame(feats)
X = X[X.d >= pd.Timestamp("2021-11-01")].copy()
X["per"] = np.where(X.d < pd.Timestamp("2024-05-15"), "前半", "后半")
X["mine"] = X.code.isin(MINE)
X["ph"] = cyc["阶段"].reindex(X.d - pd.Timedelta(days=1), method="ffill").to_numpy()  # 前一个交易日收盘的阶段
nights = {d: us_night(d) for d in X.d.unique()}
X["smh"] = [nights[d].get("SMH", np.nan) for d in X.d]; X["nvda"] = [nights[d].get("NVDA", np.nan) for d in X.d]
grp = X.groupby("d").gap.transform("mean"); X["peer_gap"] = (grp * X.groupby("d").gap.transform("size") - X.gap) / (X.groupby("d").gap.transform("size") - 1)
X.to_pickle("/home/claude/bt/_intraday_X.pkl")
pct = lambda v: f"{v*100:+.2f}%"


def sell_table(D, lab):
    cols = [("开盘卖", D.O), ("9:45卖", D.p945), ("10:00卖", D.p1000), ("10:30卖", D.p1030), ("11:30卖", D.p1130), ("收盘卖", D.C),
            ("跌破开盘15分钟低点卖", D.s_or), ("从最高回落1.5%卖", D.s_tr15), ("从最高回落2%卖", D.s_tr20), ("从最高回落3%卖", D.s_tr30),
            ("跌破分时均价线卖", D.s_vw), ("(事后)卖在最高", D.H)]
    out = []
    for n, s in cols:
        x = s / D.O - 1
        out.append({"卖法": n, "平均": pct(x.mean()), "比开盘卖好的天": f"{(x > 0).mean():.0%}", "前半": pct(x[D.per == "前半"].mean()), "后半": pct(x[D.per == "后半"].mean()),
                    "你的3只": pct(x[D.mine].mean())})
    print(f"\n== {lab}：{len(D)} 天（你的3只 {int(D.mine.sum())} 天）卖价比开盘价高多少 ==")
    print(pd.DataFrame(out).to_string(index=False))


def buy_table(D, lab):
    cols = [("开盘买", D.O), ("9:45买", D.p945), ("10:00买", D.p1000), ("10:30买", D.p1030), ("11:30买", D.p1130), ("收盘买", D.C),
            ("站上开盘15分钟高点买", D.b_or), ("上穿分时均价线买", D.b_vw), ("(事后)买在最低", D.Lo)]
    out = []
    for n, s in cols:
        x = 1 - s / D.O
        ok_ = s.notna()
        out.append({"买法": n, "比开盘便宜": pct(x[ok_].mean()), "有信号的天": f"{ok_.mean():.0%}", "前半": pct(x[ok_ & (D.per == "前半")].mean()), "后半": pct(x[ok_ & (D.per == "后半")].mean()),
                    "你的3只": pct(x[ok_ & D.mine].mean())})
    print(f"\n== {lab}：{len(D)} 天 买价比开盘价便宜多少（越大越好）==")
    print(pd.DataFrame(out).to_string(index=False))


def time_dist(D, col, lab):
    t = D[col].str.slice(0, 4)
    b = pd.cut(t.astype(int), [0, 945, 1000, 1030, 1130, 1400, 1500], labels=["9:30-9:45", "9:45-10:00", "10:00-10:30", "10:30-11:30", "13:00-14:00", "14:00-15:00"])
    print(f"{lab}：", (b.value_counts(normalize=True).sort_index() * 100).round(0).to_dict())


for thr in (0.01, 0.02, 0.03):
    H = X[(X.gap >= thr) & (X.gap < 0.095)]
    sell_table(H, f"高开≥{thr*100:.0f}%")
    time_dist(H, "t_hi", "  当天最高价出现在")
for thr in (0.01, 0.02, 0.03):
    Lw = X[(X.gap <= -thr) & (X.gap > -0.095)]
    buy_table(Lw, f"低开≥{thr*100:.0f}%")
    time_dist(Lw, "t_lo", "  当天最低价出现在")
F = X[X.gap.abs() < 0.005]
time_dist(F, "t_hi", "平开日 最高价出现在"); time_dist(F, "t_lo", "平开日 最低价出现在")

print("\n== 做T（扣成本后每次）==")
for lab, D in [("高开≥2%", X[(X.gap >= 0.02) & (X.gap < 0.095)]), ("高开1~2%", X[(X.gap >= 0.01) & (X.gap < 0.02)]), ("平开±0.5%", F),
               ("低开1~2%", X[(X.gap <= -0.01) & (X.gap > -0.02)]), ("低开≥2%", X[(X.gap <= -0.02) & (X.gap > -0.095)])]:
    print(f"{lab:8s} {len(D):5d}天 | 先卖后买：开盘卖、回落2%接回(否则收盘接) {pct(D.t_s_open_back2.mean())} 赢{(D.t_s_open_back2>0).mean():.0%}；开盘卖收盘接 {pct(D.t_s_open_close.mean())}"
          f" | 先买后卖：10点买、+2%或收盘卖 {pct(D.t_b1000_tgt2.mean())} 赢{(D.t_b1000_tgt2>0).mean():.0%}；10点买收盘卖 {pct(D.t_b1000_close.mean())}"
          f" | 前后 {pct(D[D.per=='前半'].t_s_open_back2.mean())}/{pct(D[D.per=='后半'].t_s_open_back2.mean())} ; {pct(D[D.per=='前半'].t_b1000_tgt2.mean())}/{pct(D[D.per=='后半'].t_b1000_tgt2.mean())}")

# 高开日：什么情况下开盘后还会涨（9:45之后到收盘）
H = X[(X.gap >= 0.02) & (X.gap < 0.095)].copy()
H["rest"] = H.C / H.p945 - 1; H["late_hi"] = H.t_hi.str.slice(0, 4).astype(int) > 1000
print(f"\n== 高开≥2% 的 {len(H)} 天：9:45之后到收盘的涨跌（正=该拿着，负=早卖好），以及最高价在10点以后的比例 ==")
def cond(name, m):
    a, b = H[m], H[~m]
    print(f"{name:28s} 是：{len(a):4d}天 {pct(a.rest.mean())} 高点在10点后{a.late_hi.mean():.0%} | 否：{len(b):4d}天 {pct(b.rest.mean())} 高点在10点后{b.late_hi.mean():.0%}"
          f" | 前后（是）{pct(a[a.per=='前半'].rest.mean())}/{pct(a[a.per=='后半'].rest.mean())}")
cond("开盘15分钟收在开盘价上方", H.r15 > 0)
cond("开盘15分钟量是平时1.5倍以上", H.vr15 > 1.5)
cond("同类一起高开(同类平均≥1%)", H.peer_gap >= 0.01)
cond("前一晚费城半导体(SMH)涨≥2%", H.smh >= 0.02)
cond("前一晚英伟达涨≥3%", H.nvda >= 0.03)
cond("跳空≥4%", H.gap >= 0.04)
for ph in ["冰点", "低位回升", "中高位升温", "高潮", "中高位退潮", "低位回落"]:
    cond(f"情绪阶段={ph}", H.ph == ph)
Lw = X[(X.gap <= -0.02) & (X.gap > -0.095)].copy()
Lw["rest"] = Lw.C / Lw.p945 - 1
print(f"\n== 低开≥2% 的 {len(Lw)} 天：9:45之后到收盘（正=低开后会拉回）==")
def cond2(name, m):
    a, b = Lw[m], Lw[~m]
    print(f"{name:28s} 是：{len(a):4d}天 {pct(a.rest.mean())} 收在开盘上方{(a.C>a.O).mean():.0%} | 否：{len(b):4d}天 {pct(b.rest.mean())} 收在开盘上方{(b.C>b.O).mean():.0%}")
cond2("开盘15分钟收在开盘价上方", Lw.r15 > 0)
cond2("同类一起低开(同类平均≤-1%)", Lw.peer_gap <= -0.01)
cond2("前一晚SMH跌≥2%", Lw.smh <= -0.02)
cond2("开盘15分钟量是平时1.5倍以上", Lw.vr15 > 1.5)
print("\n== 你的3只：跳空分布和高开日最高价时间 ==")
for c in MINE:
    D = X[X.code == c]
    if not len(D):
        print(NAMES[c], "没有5分钟数据"); continue
    hh = D[(D.gap >= 0.02) & (D.gap < 0.095)]
    print(NAMES[c], f"{len(D)}天，高开≥2% {len(hh)}天（{len(hh)/len(D):.0%}），低开≥2% {((D.gap<=-0.02)&(D.gap>-0.095)).sum()}天；高开≥2%后收在开盘下方 {(hh.C<hh.O).mean():.0%}")
