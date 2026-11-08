"""交易台（GitHub Pages）"市场环境"——每日计算（由 .github/workflows/env-page.yml 在数据管线跑完后运行）

用法:
  python pages/env_pipeline.py --data <data 分支目录> --jsq <本仓库目录> --static <gh-pages/env_static.json> --out env.json [--prev 旧env.json]

输出 env.json：
- a / us：当天状态、最近500个交易日走势、A股情绪温度各档之后60天的历史统计（每天重算）
- live：页面在盘中用实时行情估算情绪温度、全A等权和美股200日线位置所需的基准数据
- findings：研究结论文字，来自 env_static.json（由研究会话维护）
标准输出第一行是 CHANGES: …（和上一份 env.json 比的状态变化）。

口径:
- A股情绪温度: 全A剔除ST和上市不满20天的股票，11个指标（涨停占比、跌停占比、涨停减跌停占比、炸板率、连板高度、
  昨日涨停今日涨幅、上涨占比、成交额热度、创一年新高减新低占比、站上20日线占比、站上60日线占比），
  部分取5日均值，各自换算成过去250天里的分位（至少200天），按含义统一方向后等权平均 ×100。
- A股牛熊: 全A等权指数（每日等权平均涨跌幅连乘）在200日线上/下。
- 美股: 纳指100/标普500 收盘 vs 200日线；VIX ≥20 为恐慌；跌破 = 先连续20天站上200日线，再收盘低于200日线2%以上；
  认错线 = 最近一次跌破日收盘 × 0.85。实时换算用 QQQ / SPY（币安有对应永续合约）。
"""
import argparse, glob, json, os, sys
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--jsq", required=True)
ap.add_argument("--out", required=True); ap.add_argument("--prev", default=None)
ap.add_argument("--static", required=True)
ap.add_argument("--fund", default=None)   # fund 分支目录（可选）：美股财报日
args = ap.parse_args()
sys.path.insert(0, args.jsq)
os.environ["MARKET_DATA"] = args.data
from market_data import load  # noqa: E402


def r(x, n=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


# ============================================================ A股：面板
cols = ["date", "code", "high", "low", "close", "preclose", "amount", "tradestatus", "pctChg", "isST"]
parts = []
for f in sorted(glob.glob(f"{args.data}/a_share/daily/*/*.csv.xz")):
    if int(f.split("/")[-2]) < 2014:
        continue
    d = pd.read_csv(f, usecols=cols, dtype={"date": str, "code": str})
    for c in ["high", "low", "close", "preclose", "amount", "pctChg"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
    d["tradestatus"] = pd.to_numeric(d["tradestatus"], errors="coerce").fillna(0).astype("int8")
    d["isST"] = pd.to_numeric(d["isST"], errors="coerce").fillna(0).astype("int8")
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
df = df[df.code.str.match(r"^(sh\.6|sz\.0|sz\.3)")]
dates_s = np.sort(df.date.unique()); codes = np.sort(df.code.unique())
di = pd.Index(dates_s).get_indexer(df.date); ci = pd.Index(codes).get_indexer(df.code)
P = {}
for c, dt, fill in [("high", "float32", np.nan), ("close", "float32", np.nan), ("preclose", "float32", np.nan),
                    ("amount", "float32", np.nan), ("pctChg", "float32", np.nan), ("tradestatus", "int8", 0), ("isST", "int8", 0)]:
    m = np.full((len(dates_s), len(codes)), fill, dtype=dt)
    m[di, ci] = df[c].to_numpy()
    P[c] = m
del df, parts
dates = pd.to_datetime(dates_s)

# ============================================================ A股：每日情绪指标
traded = (P["tradestatus"] == 1) & np.isfinite(P["close"]) & (P["amount"] > 0)
age = np.cumsum(traded, axis=0)
ok = traded & (age >= 20) & (P["isST"] == 0)
pct = np.where(traded, P["pctChg"], np.nan).astype("float64")
close = P["close"].astype("float64")
kc = np.char.startswith(codes.astype(str), "sh.68"); cy = np.char.startswith(codes.astype(str), "sz.30")
reform = (dates >= pd.Timestamp("2020-08-24"))[:, None]
lim = np.where(P["isST"] == 1, 0.05, 0.10)
lim = np.where(kc[None, :] | (cy[None, :] & reform), 0.20, lim)
pc = P["preclose"].astype("float64")
up = np.floor(pc * (1 + lim) * 100 + 0.5) / 100
dn = np.floor(pc * (1 - lim) * 100 + 0.5) / 100
zt = ok & (np.abs(close - up) < 0.0051)
dtm = ok & (np.abs(close - dn) < 0.0051)
touched = ok & (P["high"].astype("float64") >= up - 0.0051)
streak = np.zeros_like(zt, dtype=np.int16); streak[0] = zt[0]
for t in range(1, len(zt)):
    streak[t] = (streak[t - 1] + 1) * zt[t]
ret = np.where(traded, P["pctChg"] / 100.0, 0.0)
adj = np.where(traded, np.cumprod(1 + ret, axis=0), np.nan)
A = pd.DataFrame(adj)
hi250 = A.rolling(250, min_periods=200).max().to_numpy(); lo250 = A.rolling(250, min_periods=200).min().to_numpy()
ma20 = A.rolling(20, min_periods=15).mean().to_numpy(); ma60 = A.rolling(60, min_periods=45).mean().to_numpy()
okh = ok & (age >= 250); n_ok = ok.sum(1)
prev_zt = np.vstack([np.zeros((1, zt.shape[1]), bool), zt[:-1]]); pz = prev_zt & ok
prem = np.where(pz.sum(1) > 0, np.nansum(np.where(pz, pct, 0), 1) / np.maximum(pz.sum(1), 1), np.nan)
with np.errstate(all="ignore"):
    ew = np.nanmean(np.where(ok, pct, np.nan), 1) / 100
amt = np.nansum(np.where(traded, P["amount"], 0), 1) / 1e8
s = pd.DataFrame({
    "n": n_ok, "涨停": zt.sum(1), "跌停": dtm.sum(1),
    "炸板率": 1 - zt.sum(1) / np.maximum(touched.sum(1), 1),
    "连板高度": np.where(ok, streak, 0).max(1), "昨日涨停今日涨幅": prem,
    "上涨占比": (ok & (pct > 0)).sum(1) / np.maximum(n_ok, 1), "成交额亿": amt,
    "新高减新低占比": ((okh & (adj >= hi250 - 1e-12)).sum(1) - (okh & (adj <= lo250 + 1e-12)).sum(1)) / np.maximum(okh.sum(1), 1),
    "站上20日线占比": (ok & (adj > ma20)).sum(1) / np.maximum(n_ok, 1),
    "站上60日线占比": (ok & (adj > ma60)).sum(1) / np.maximum(n_ok, 1), "等权日收益": ew,
}, index=dates)
s["成交额热度"] = s["成交额亿"].rolling(20).mean() / s["成交额亿"].rolling(250).mean()
s["等权指数"] = (1 + s["等权日收益"].fillna(0)).cumprod()
s["涨停占比"] = s["涨停"] / s["n"]; s["跌停占比"] = s["跌停"] / s["n"]; s["涨跌停差占比"] = (s["涨停"] - s["跌停"]) / s["n"]

# ============================================================ A股：情绪温度
IND = {"涨停占比": 5, "跌停占比": 5, "涨跌停差占比": 5, "炸板率": 5, "连板高度": 5, "昨日涨停今日涨幅": 5,
       "上涨占比": 5, "成交额热度": 1, "新高减新低占比": 5, "站上20日线占比": 1, "站上60日线占比": 1}


def pct_rank(x, win=250):
    return x.rolling(win, min_periods=200).apply(lambda a: (a[-1] > a[:-1]).mean() + 0.5 * (a[-1] == a[:-1]).mean(), raw=True)


for k, sm in IND.items():
    v = s[k].rolling(sm).mean() if sm > 1 else s[k]
    s[k + "_分位"] = pct_rank(v)
HOT = ["涨停占比", "涨跌停差占比", "连板高度", "昨日涨停今日涨幅", "上涨占比", "新高减新低占比", "站上20日线占比", "站上60日线占比", "成交额热度"]
COLD = ["跌停占比", "炸板率"]
s["温度"] = (s[[h + "_分位" for h in HOT]].sum(axis=1) + (1 - s[[c + "_分位" for c in COLD]]).sum(axis=1)) / 11 * 100
s["ma200"] = s["等权指数"].rolling(200).mean()
s["牛熊"] = pd.Series(np.where(s["等权指数"] > s["ma200"], "牛", "熊"), index=s.index).shift(1)
s["fwd60"] = s["等权指数"].shift(-60) / s["等权指数"] - 1

last = s.index[-1]; L = s.loc[last]
band = lambda t: "冰点" if t < 20 else "偏冷" if t < 40 else "中性" if t <= 60 else "偏热" if t <= 80 else "过热"
recent = s.loc[s.index[-10]:]
a_today = dict(date=str(last.date()), regime="牛市" if L["等权指数"] > L["ma200"] else "熊市",
               ew_vs_ma200=r(L["等权指数"] / L["ma200"] - 1, 4), temp=r(L["温度"], 1), band=band(L["温度"]),
               temp_min10=r(recent["温度"].min(), 1), temp_min10_date=str(recent["温度"].idxmin().date()),
               amount=r(L["成交额亿"], 0), heat=r(L["成交额热度"], 2), zt=int(L["涨停"]), dt=int(L["跌停"]),
               lb=int(L["连板高度"]), adv=r(L["上涨占比"], 3))
w = s.loc["2016-01-01":].dropna(subset=["温度", "fwd60"]).copy()
w["档"] = pd.cut(w["温度"], [-1, 20, 40, 60, 80, 101], labels=["冰点", "偏冷", "中性", "偏热", "过热"])
w["reg"] = w["牛熊"].map({"牛": "牛市", "熊": "熊市"})
stats = []
for b, gb in w.groupby("档", observed=True):
    row = dict(band=str(b), all_ret=r(gb.fwd60.mean(), 4), all_up=r((gb.fwd60 > 0).mean(), 3), all_n=len(gb))
    for rg, key in [("熊市", "bear"), ("牛市", "bull")]:
        x = gb[gb.reg == rg]
        row[f"{key}_ret"] = r(x.fwd60.mean(), 4) if len(x) else None
        row[f"{key}_up"] = r((x.fwd60 > 0).mean(), 3) if len(x) else None
        row[f"{key}_n"] = len(x)
    stats.append(row)
ser = s.loc[s.index[-500]:]
a_series = [dict(d=str(i.date()), t=r(v.温度, 1), ew=r(v.等权指数, 4), ma=r(v.ma200, 4)) for i, v in ser.iterrows()]

# ============================================================ 美股
d = load.us_daily(["^NDX", "^GSPC", "^VIX"])


def frame(t):
    px = d[d.ticker == t].set_index("date")["close"]
    vix = d[d.ticker == "^VIX"].set_index("date")["close"].reindex(px.index).ffill()
    f = pd.DataFrame({"px": px, "vix": vix})
    f["ma200"] = f.px.rolling(200).mean()
    f["hi252"] = f.px.rolling(252, min_periods=200).max()
    return f.dropna(subset=["ma200"])


def breaks(f, brk=0.02, arm=20):
    above = (f.px > f.ma200).to_numpy(); deep = (f.px < f.ma200 * (1 - brk)).to_numpy()
    out, run, armed = [], 0, False
    for i in range(len(f)):
        run = run + 1 if above[i] else 0
        if run >= arm:
            armed = True
        if armed and deep[i]:
            out.append(i); armed = False
    return out


n = frame("^NDX"); sp = frame("^GSPC")
nl, sl = n.iloc[-1], sp.iloc[-1]
us_state = ("熊市" if nl.px < nl.ma200 else "牛市") + ("·恐慌" if nl.vix >= 20 else "·平静")
t0 = breaks(n)[-1]; bc = n.px.iloc[t0]
us_today = dict(date=str(n.index[-1].date()), state=us_state, ndx=r(nl.px, 1), ndx_ma200=r(nl.ma200, 1),
                ndx_vs=r(nl.px / nl.ma200 - 1, 4), ndx_dd52=r(nl.px / nl.hi252 - 1, 4), spx=r(sl.px, 1), spx_ma200=r(sl.ma200, 1),
                spx_vs=r(sl.px / sl.ma200 - 1, 4), vix=r(nl.vix, 2), break_date=str(n.index[t0].date()), break_close=r(bc, 1),
                stop_line=r(bc * 0.85, 0))
us_series = [dict(d=str(i.date()), ndx=r(v.px, 1), ma=r(v.ma200, 1), vix=r(v.vix, 2)) for i, v in n.iloc[-500:].iterrows()]

# ============================================================ 盘中估算用的基准
LIVE5 = {"涨停占比": "hot", "跌停占比": "cold", "涨跌停差占比": "hot", "上涨占比": "hot"}   # 盘中能直接算的4个（炸板率要最高价，盘中沿用收盘分位）
other = [k for k in IND if k not in LIVE5]
live_a = dict(
    date=a_today["date"],
    last4={k: [r(x, 6) for x in s[k].iloc[-4:]] for k in LIVE5},                         # 5日均值要用的前4天
    prev249={k: [r(x, 6) for x in s[k].rolling(5).mean().iloc[-249:]] for k in LIVE5},   # 排分位用的前249个平滑值
    dir=dict(LIVE5),
    other_pct={k: r(s[k + "_分位"].iloc[-1], 4) for k in other},                        # 其余6个指标沿用最近收盘的分位
    other_dir={k: ("cold" if k in COLD else "hot") for k in other},
    ew_last=r(s["等权指数"].iloc[-1], 6), ew_sum199=r(s["等权指数"].iloc[-199:].sum(), 6),
    amount_avg250=r(s["成交额亿"].iloc[-250:].mean(), 1),
)
# 盘中要拉行情的股票：最近10个交易日有成交、最近一次成交时不是ST、到下个交易日上市满20天
last_tr = np.where(traded[::-1].any(0), len(dates) - 1 - traded[::-1].argmax(0), -1)
recent_ok = last_tr >= len(dates) - 10
st_last = P["isST"][np.clip(last_tr, 0, None), np.arange(len(codes))] == 1
elig = recent_ok & ~st_last & (age[-1] >= 19)
live_a["codes"] = [c.replace(".", "") for c in codes[elig]]

# ---------------- 行业（主线）：证监会行业，收盘时各行业的涨停数、平均涨跌、成交占比 vs 近20日平均占比
SHORT = {"计算机、通信和其他电子设备制造业": "电子/通信设备", "专用设备制造业": "专用设备", "化学原料和化学制品制造业": "化工",
         "软件和信息技术服务业": "软件/IT服务", "电气机械和器材制造业": "电气设备", "医药制造业": "医药", "通用设备制造业": "通用设备",
         "汽车制造业": "汽车", "橡胶和塑料制品业": "橡胶塑料", "非金属矿物制品业": "建材", "金属制品业": "金属制品",
         "电力、热力生产和供应业": "电力热力", "有色金属冶炼和压延加工业": "有色冶炼", "铁路、船舶、航空航天和其他运输设备制造业": "航空航天/船舶",
         "仪器仪表制造业": "仪器仪表", "互联网和相关服务": "互联网", "资本市场服务": "券商", "货币金融服务": "银行",
         "酒、饮料和精制茶制造业": "酒饮料", "有色金属矿采选业": "有色矿采", "煤炭开采和洗选业": "煤炭", "黑色金属冶炼和压延加工业": "钢铁",
         "土木工程建筑业": "建筑", "生态保护和环境治理业": "环保", "农副食品加工业": "农副食品", "纺织服装、服饰业": "服装",
         "研究和试验发展": "研发服务", "专业技术服务业": "专业技术服务", "电信、广播电视和卫星传输服务": "通信服务",
         "广播、电视、电影和录音制作业": "影视", "新闻和出版业": "出版", "保险业": "保险", "石油和天然气开采业": "油气开采",
         "石油加工、炼焦和核燃料加工业": "石化炼焦", "水上运输业": "航运", "航空运输业": "航空", "道路运输业": "公路运输"}
import re as _re
def _short(x):
    if not isinstance(x, str) or not x:
        return None
    x = _re.sub(r"^[A-Z]\d{2}", "", x)
    if x in SHORT:
        return SHORT[x]
    return x.split("和")[0].split("、")[0].replace("制造业", "").rstrip("业")[:8]
_ind = pd.read_csv(f"{args.data}/a_share/meta/industry.csv", dtype=str)
_imap = dict(zip(_ind.code, _ind.industry.map(_short)))
ind_of = np.array([_imap.get(c) for c in codes], dtype=object)
names = sorted({x for x in ind_of if isinstance(x, str) and x})
idx_of = {nm: i for i, nm in enumerate(names)}
code_ind = np.array([idx_of.get(x, -1) if isinstance(x, str) else -1 for x in ind_of])
amt_m = np.where(traded, P["amount"], 0).astype("float64")
tot = amt_m.sum(1, keepdims=True)
sh = np.zeros((len(dates), len(names)))
for j in range(len(names)):
    sh[:, j] = amt_m[:, code_ind == j].sum(1) / np.maximum(tot[:, 0], 1)
share20 = sh[-21:-1].mean(0)                      # 不含当天的前20天平均占比
last_pct = np.where(ok[-1], pct[-1], np.nan)
top = []
for j, nm in enumerate(names):
    m = (code_ind == j) & ok[-1]
    if m.sum() < 15 or sh[-21:-1, j].mean() < 0.005:   # 太小的行业不排（占全市场成交不到0.5%）
        continue
    top.append(dict(name=nm, n=int(m.sum()), zt=int(zt[-1][m].sum()), avg=r(np.nanmean(last_pct[m]) / 100, 4),
                    share=r(sh[-1, j], 4), share20=r(sh[-21:-1, j].mean(), 4)))
top.sort(key=lambda x: (x["share"] or 0) / max(x["share20"] or 1e-9, 1e-9), reverse=True)   # 成交占比比平时放大最多的在前
a_today["top_ind"] = top[:8]
live_a["ind_names"] = names
live_a["ind_share20"] = [r(x, 5) for x in sh[-20:].mean(0)]   # 下个交易日盘中比较用：含最近一天的20天平均
_elig_codes = codes[elig]
_pos = {c: i for i, c in enumerate(codes)}
live_a["code_ind"] = [int(code_ind[_pos[c]]) for c in _elig_codes]

live_us = {}
for t in ["QQQ", "SPY"]:
    px = load.us_daily(t).set_index("date")["close"]
    px = px[px.index <= n.index[-1]]
    live_us[t] = dict(date=str(px.index[-1].date()), close=r(px.iloc[-1], 2), ma200=r(px.iloc[-200:].mean(), 2),
                      sum199=r(px.iloc[-199:].sum(), 2), hi252=r(px.iloc[-252:].max(), 2))
qq = load.us_daily("QQQ").set_index("date")["close"]
live_us["QQQ"]["stop_line"] = r(qq.loc[n.index[t0]] * 0.85, 2)
# 币安上市不满200个交易日的大宗合约，大方向用美国期货日线的200日线（上个收盘）
live_fut = {}
for sym, tk in {"XPTUSDT": "PL=F", "XPDUSDT": "PA=F", "COPPERUSDT": "HG=F", "NATGASUSDT": "NG=F"}.items():
    try:
        px = load.us_daily(tk).set_index("date")["close"].dropna()
    except Exception:
        continue
    if len(px) < 200:
        continue
    ma = px.iloc[-200:].mean()
    live_fut[sym] = dict(ticker=tk, date=str(px.index[-1].date()), close=r(px.iloc[-1], 4), ma200=r(ma, 4), vs=r(px.iloc[-1] / ma - 1, 4))
live = dict(a=live_a, us=live_us, fut=live_fut)
static = json.load(open(args.static, encoding="utf-8"))
findings = static["findings"]
earn = {}
if args.fund and os.path.exists(f"{args.fund}/us/earnings.csv"):
    _e = pd.read_csv(f"{args.fund}/us/earnings.csv")
    _today = str(pd.Timestamp(us_today["date"]).date())
    for t, g in _e.groupby("ticker"):
        nxt = sorted(d for d in g.date.astype(str) if d >= _today)
        if nxt:
            earn[t] = nxt[0]
env = dict(asof=max(a_today["date"], us_today["date"]), a=dict(today=a_today, stats=stats, series=a_series),
           us=dict(today=us_today, series=us_series), live=live, findings=findings,
           contract_stats=static.get("contract_stats"), contract_stats_note=static.get("contract_stats_note"), earnings=earn)
json.dump(env, open(args.out, "w"), ensure_ascii=False, separators=(",", ":"))

# ============================================================ 变化摘要
changes = []
if args.prev and os.path.exists(args.prev):
    old = json.load(open(args.prev))
    oa, ou = old["a"]["today"], old["us"]["today"]
    if a_today["date"] == oa["date"] and us_today["date"] == ou["date"]:
        changes.append("NO_NEW_DATA")
    if a_today["regime"] != oa["regime"]:
        changes.append(f"A股牛熊变化：{oa['regime']} → {a_today['regime']}")
    if a_today["band"] != oa["band"] and (a_today["band"] in ("冰点", "过热") or oa["band"] in ("冰点", "过热")):
        changes.append(f"A股情绪温度：{oa['band']}({oa['temp']}) → {a_today['band']}({a_today['temp']})")
    if us_today["state"] != ou["state"]:
        changes.append(f"美股状态：{ou['state']} → {us_today['state']}")
    if (us_today["spx_vs"] < 0) != (ou["spx_vs"] < 0):
        changes.append(f"标普{'跌破' if us_today['spx_vs'] < 0 else '重新站上'}200日线（{us_today['spx']} vs {us_today['spx_ma200']}）")
    if us_today["ndx"] <= us_today["stop_line"] and ou["ndx"] > ou.get("stop_line", 0):
        changes.append(f"纳指跌到认错线（{us_today['ndx']} ≤ {us_today['stop_line']}）")
    if us_today["break_date"] != ou["break_date"]:
        changes.append(f"纳指新一次跌破200日线（{us_today['break_date']}），认错线更新为 {us_today['stop_line']}")
print("CHANGES: " + (" | ".join(changes) if changes else "无状态变化"))
print(f"A股 {a_today['date']} {a_today['regime']}·{a_today['band']} 温度{a_today['temp']} | 美股 {us_today['date']} {us_today['state']} 纳指{us_today['ndx']} 标普{us_today['spx']} VIX{us_today['vix']}")
