import sys, os
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load
import numpy as np, pandas as pd
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_cn_link_bt.py")).read().split("rows, detail = [], []")[0])
START, END = "2021-11-01", "2026-11-12"
print("== 按天聚合（同一天几只跟随股取平均）后的 t 值 ==")
for tk, v in PAIRS.items():
    u = us_window(tk).rename("us")
    fol = v.get("a", []) + v.get("idx", [])
    F = pd.concat([a_frame(c).join(u, how="inner").loc[START:END].assign(code=c) for c in fol]).dropna(subset=["us","oc"])
    F = F[F.us != 0]
    day = F.groupby(level=0).agg(us=("us","first"), oc=("oc","mean"), gap=("gap","mean"), d5=("d5","mean"))
    hi, lo = day.us.quantile(.9), day.us.quantile(.1); base = day.oc.mean()
    out = []
    for tag, m in [("涨", day.us >= hi), ("跌", day.us <= lo)]:
        y = day[m].oc - base
        out.append(f"大{tag}夜 {len(y)}天 开盘后多{y.mean()*100:+.2f}% t={y.mean()/y.std()*np.sqrt(len(y)):+.1f}")
    print(f"{v['name']:6s}", " | ".join(out))
# 大周期稳健性
print("\n== 大周期分段 ==")
nd = US["^NDX"].dropna(); nbull = (nd > nd.rolling(200).mean())
for code in ["sh.000300", "sh.000852"]:
    g = ix[ix.code == code].set_index("date").close.sort_index()
    ab = g > g.rolling(200).mean(); nb = nbull.reindex(g.index, method="ffill").shift(1)
    f60 = g.shift(-60) / g - 1
    d = pd.DataFrame({"ab": ab, "nb": nb, "f": f60}).dropna()
    for y0, y1 in [("2010-06-01", "2017-12-31"), ("2018-01-01", "2026-11-12"), ("2021-11-01", "2026-11-12")]:
        x = d.loc[y0:y1].iloc[::5]
        t = x.groupby(["ab", "nb"]).f.agg(["mean", "count"])
        print(code, y0[:4], y1[:4], {f"A{'牛' if a else '熊'}美{'牛' if b else '熊'}": (round(m*100,1), int(c)) for (a, b), (m, c) in t.iterrows()})
    # A熊美牛 段数
    st = (~d.ab & (d.nb == True)).astype(int)
    seg = (st.diff() == 1).sum()
    print("  A熊美牛 段数(2010→):", int(seg))
