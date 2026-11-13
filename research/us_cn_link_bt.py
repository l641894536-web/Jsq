"""美股当晚 → 第二天A股：关联有多强、开盘追不追、拿几天。
时间对齐：A股某天 D 开盘前能看到的美股信息 = 上一个A股交易日收盘（北京15:00 = 美东凌晨）之后的美股交易日。
  美股这段涨跌 = 美股 收盘(最后一个 ≤ D-1 的美股日) / 收盘(最后一个 ≤ 上一个A股日-1 的美股日) - 1
A股：跳空 gap = 开盘/前收-1；开盘后 oc = 收盘/开盘-1；之后5天 d5 = 第4个交易日收盘/当天开盘-1（都按交易所前收，除权不影响）。
条件：美股这段涨跌落在自己的前10% / 后10%（按整个样本分位），对比全部日子的平均。
另：大周期 —— A股自己的200日线 × 纳指200日线 四种组合，之后60天A股涨跌（2010→）。
用法: python3 us_cn_link_bt.py [start] [end]
"""
import sys, os, json
sys.path.insert(0, "/home/claude/jsq")
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load
import numpy as np, pandas as pd

START = sys.argv[1] if len(sys.argv) > 1 else "2021-11-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-11-12"
CACHE = "/home/claude/bt/_cn_link_a.pkl"

PAIRS = {  # 美股 → A股跟随者
    "^NDX": {"name": "纳指100", "idx": ["sh.000300", "sz.399006", "sh.000852", "sh.000001"]},
    "SMH": {"name": "半导体ETF", "a": ["sz.002371", "sh.688012", "sh.688981", "sh.688256", "sh.603986", "sh.688008"]},
    "NVDA": {"name": "英伟达", "a": ["sz.300308", "sz.300502", "sh.601138", "sz.002463", "sz.300476", "sz.300394"]},
    "AMD": {"name": "AMD", "a": ["sz.002156", "sh.688041"]},
    "MU": {"name": "美光", "a": ["sh.603986", "sz.301308", "sh.688525", "sh.688008"]},
    "AAPL": {"name": "苹果", "a": ["sz.002475", "sz.002241", "sz.300433", "sz.002938"]},
    "TSLA": {"name": "特斯拉", "a": ["sh.601689", "sz.002050", "sz.002594", "sz.300750"]},
    "KWEB": {"name": "中概互联", "idx": ["sh.000300", "sz.399006", "sh.000852"]},
    "GC=F": {"name": "黄金期货", "a": ["sh.601899", "sh.600547", "sh.600489"]},
    "HG=F": {"name": "铜期货", "a": ["sh.600362", "sh.601899", "sh.603993"]},
    "CL=F": {"name": "原油期货", "a": ["sh.600938", "sh.601857"]},
}
NAMES = {}

if os.path.exists(CACHE):
    A = pd.read_pickle(CACHE)
else:
    codes = sorted({c for v in PAIRS.values() for c in v.get("a", [])})
    A = load.a_share(start="2015-06-01", codes=codes, adjust=None)[["date", "code", "open", "close", "preclose", "tradestatus"]]
    A.to_pickle(CACHE)
ix = load.a_share_index(start="2009-01-01")[["date", "code", "open", "close", "preclose"]]
ix["tradestatus"] = "1"
A = pd.concat([A, ix])
A = A[A.tradestatus.astype(str) == "1"]
sb = load.a_share_stocks().set_index("code").code_name.to_dict()
sb.update({"sh.000300": "沪深300", "sz.399006": "创业板指", "sh.000852": "中证1000", "sh.000001": "上证指数"})
US = load.us_daily(list(PAIRS), start="2009-01-01").pivot(index="date", columns="ticker", values="close").sort_index()

adates = pd.DatetimeIndex(sorted(A.date.unique()))
# 每个A股日 D：能看到的美股窗口 (prevA-1, D-1]
prevA = pd.Series(adates[:-1], index=adates[1:])


def us_window(tk):
    c = US[tk].dropna()
    idx = c.index
    out = {}
    for D, P in prevA.items():
        j1 = idx.searchsorted(D - pd.Timedelta(days=1), side="right") - 1   # 最后一个 ≤ D-1
        j0 = idx.searchsorted(P - pd.Timedelta(days=1), side="right") - 1   # 最后一个 ≤ prevA-1
        if j0 < 0 or j1 <= j0:
            out[D] = 0.0 if j1 == j0 and j0 >= 0 else np.nan   # 中间没有美股交易日 = 没新信息
            continue
        out[D] = c.iloc[j1] / c.iloc[j0] - 1
    return pd.Series(out)


def a_frame(code):
    g = A[A.code == code].set_index("date").sort_index()
    g = g[(g.open > 0) & (g.preclose > 0)]
    f = pd.DataFrame({"gap": g.open / g.preclose - 1, "oc": g.close / g.open - 1, "cc": g.close / g.preclose - 1})
    f["d5"] = g.close.shift(-4) / g.open - 1
    return f


rows, detail = [], []
cut = None
for tk, v in PAIRS.items():
    u = us_window(tk).rename("us")
    sub = u.loc[START:END].dropna()
    sub = sub[sub != 0]
    hi, lo = sub.quantile(0.9), sub.quantile(0.1)
    followers = v.get("a", []) + v.get("idx", [])
    frames = []
    for code in followers:
        f = a_frame(code).join(u, how="inner").loc[START:END].dropna(subset=["us", "gap", "oc"])
        f = f[f.us != 0]
        if len(f) < 200:
            continue
        f["code"] = code
        frames.append(f)
    if not frames:
        continue
    F = pd.concat(frames)
    dates = sorted(F.index.unique()); mid = dates[len(dates) // 2]; cut = mid

    def stats(x, who):
        r = {"美股": v["name"], "A股": who, "天数": len(x),
             "跳空相关": x.us.corr(x.gap), "开盘后相关": x.us.corr(x.oc), "跳空β": np.polyfit(x.us, x.gap, 1)[0]}
        for tag, m in [("大涨夜", x.us >= hi), ("大跌夜", x.us <= lo)]:
            y = x[m]
            r[f"{tag}次数"] = len(y)
            r[f"{tag}美股"] = y.us.mean()
            r[f"{tag}跳空"] = y.gap.mean()
            r[f"{tag}开盘后"] = y.oc.mean() - x.oc.mean()
            r[f"{tag}开盘后涨%"] = (y.oc > 0).mean()
            r[f"{tag}5天"] = y.d5.mean() - x.d5.mean()
            h1, h2 = y[y.index < mid], y[y.index >= mid]
            r[f"{tag}开盘后前后"] = (h1.oc.mean() - x[x.index < mid].oc.mean(), h2.oc.mean() - x[x.index >= mid].oc.mean())
            r[f"{tag}5天前后"] = (h1.d5.mean() - x[x.index < mid].d5.mean(), h2.d5.mean() - x[x.index >= mid].d5.mean())
        return r
    rows.append(stats(F, "（" + "、".join(sb.get(c, c) for c in followers if c in set(F.code)) + "）合计"))
    for code in followers:
        x = F[F.code == code]
        if len(x):
            detail.append(stats(x, sb.get(code, code)))
    NAMES[tk] = (hi, lo)

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 60)
R = pd.DataFrame(rows); D = pd.DataFrame(detail)
fmt = lambda df: df.map(lambda z: (f"{z*100:+.2f}%" if isinstance(z, float) and abs(z) < 5 and not np.isnan(z) else
                                    (f"({z[0]*100:+.2f}/{z[1]*100:+.2f})" if isinstance(z, tuple) else z)))
cols_main = ["美股", "A股", "天数", "跳空相关", "开盘后相关", "跳空β"]
print(f"区间 {START} → {END}，分段点 {cut.date() if cut is not None else None}")
print("美股前10%/后10%阈值:", {k: (round(a * 100, 2), round(b * 100, 2)) for k, (a, b) in NAMES.items()})
print("\n== 相关性（合计）==")
print(R[cols_main].assign(**{c: R[c].round(2) for c in ["跳空相关", "开盘后相关", "跳空β"]}).to_string(index=False))
for tag in ["大涨夜", "大跌夜"]:
    cs = ["美股", f"{tag}次数", f"{tag}美股", f"{tag}跳空", f"{tag}开盘后", f"{tag}开盘后涨%", f"{tag}开盘后前后", f"{tag}5天", f"{tag}5天前后"]
    print(f"\n== {tag}（开盘后/5天 = 比平常多出的部分）==")
    print(fmt(R[cs]).to_string(index=False))
print("\n== 逐只 ==")
cs = ["美股", "A股", "天数", "跳空相关", "开盘后相关", "大涨夜跳空", "大涨夜开盘后", "大涨夜5天", "大跌夜跳空", "大跌夜开盘后", "大跌夜5天"]
print(fmt(D[cs].assign(跳空相关=D.跳空相关.round(2), 开盘后相关=D.开盘后相关.round(2))).to_string(index=False))
R.to_pickle("/home/claude/bt/_cn_link_R.pkl"); D.to_pickle("/home/claude/bt/_cn_link_D.pkl")

# ---------------- 大周期：A股200日线 × 纳指200日线 → 之后60天
print("\n== 大周期（2010→）：A股指数之后60天 ==")
nd = US["^NDX"].dropna(); nbull = (nd > nd.rolling(200).mean())
for code in ["sh.000300", "sh.000852", "sz.399006"]:
    g = ix[ix.code == code].set_index("date").close.sort_index()
    ab = g > g.rolling(200).mean()
    nb = nbull.reindex(g.index, method="ffill").shift(1)
    f60 = g.shift(-60) / g - 1
    d = pd.DataFrame({"ab": ab, "nb": nb, "f": f60}).loc["2010-06-01":END].dropna()
    d = d.iloc[::5]   # 每周取一次，减少重叠
    t = d.groupby(["ab", "nb"]).f.agg(["mean", "count", lambda s: (s > 0).mean()])
    t.index = [f"A{'牛' if a else '熊'}·美{'牛' if b else '熊'}" for a, b in t.index]
    t.columns = ["60天平均", "样本(周)", "上涨比例"]
    print(sb.get(code), "\n", t.assign(**{"60天平均": (t["60天平均"] * 100).round(2), "上涨比例": (t["上涨比例"] * 100).round(0)}).to_string())
    # 周收益相关
wk = lambda s: s.resample("W-FRI").last().pct_change()
for y0, y1 in [("2016-01-01", "2021-10-31"), ("2021-11-01", END)]:
    a = wk(ix[ix.code == "sh.000300"].set_index("date").close.sort_index()).loc[y0:y1]
    b = wk(nd).loc[y0:y1]
    print(f"沪深300 vs 纳指 周涨跌相关 {y0[:7]}~{y1[:7]}: {a.corr(b):.2f}")
