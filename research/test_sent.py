"""检验每个情绪指标：把它在过去一年里的相对位置（0~100%分位）分成五档，看之后20天、60天全A等权指数的平均涨跌。
分前后两半（2016–2020 / 2021–2026）和牛熊（等权指数在200日线上/下）分别看，只有方向一致的才算数。"""
import numpy as np
import pandas as pd

s = pd.read_csv("sentiment_daily.csv", index_col=0, parse_dates=True)
s["涨停占比"] = s["涨停"] / s["n"]
s["跌停占比"] = s["跌停"] / s["n"]
s["涨跌停差占比"] = (s["涨停"] - s["跌停"]) / s["n"]
IND = {  # 指标: 用几天平均
    "涨停占比": 5, "跌停占比": 5, "涨跌停差占比": 5, "炸板率": 5, "连板高度": 5, "昨日涨停今日涨幅": 5,
    "上涨占比": 5, "成交额热度": 1, "新高减新低占比": 5, "站上20日线占比": 1, "站上60日线占比": 1,
}
idx = s["等权指数"]
ma200 = idx.rolling(200).mean()
s["牛熊"] = np.where(idx > ma200, "牛(等权指数在200日线上)", "熊(等权指数在200日线下)")
for H in (20, 60):
    s[f"fwd{H}"] = idx.shift(-H) / idx - 1


def pct_rank(x, win=250):
    return x.rolling(win, min_periods=200).apply(lambda a: (a[-1] > a[:-1]).mean() + 0.5 * (a[-1] == a[:-1]).mean(), raw=True)


rows = {}
for k, sm in IND.items():
    v = s[k].rolling(sm).mean() if sm > 1 else s[k]
    s[k + "_分位"] = pct_rank(v)

w = s.loc["2016-01-01":].dropna(subset=["fwd20"]).copy()
w["half"] = np.where(w.index < "2021-01-01", "2016-20", "2021-26")
w["regime"] = w["牛熊"].shift(1)
labels = ["最冷", "偏冷", "中", "偏热", "最热"]
out = []
for k in IND:
    q = pd.cut(w[k + "_分位"], [-0.01, 0.2, 0.4, 0.6, 0.8, 1.01], labels=labels)
    for H in (20, 60):
        d = w.assign(q=q).dropna(subset=["q", f"fwd{H}"])
        for grp_name, grp in [("全部", d)] + [(h, x) for h, x in d.groupby("half")] + [(r, x) for r, x in d.groupby("regime")]:
            m = grp.groupby("q", observed=True)[f"fwd{H}"].mean()
            out.append(dict(指标=k, H=H, 样本=grp_name, **{l: m.get(l, np.nan) for l in labels},
                            热减冷=m.get("最热", np.nan) - m.get("最冷", np.nan)))
o = pd.DataFrame(out)
o.to_csv("sent_test.csv", index=False)
pd.set_option("display.width", 250)
for H in (20, 60):
    t = o[o.H == H].pivot(index="指标", columns="样本", values="热减冷")
    t = t[["全部", "2016-20", "2021-26", "牛(等权指数在200日线上)", "熊(等权指数在200日线下)"]]
    sign = np.sign(t[["2016-20", "2021-26", "牛(等权指数在200日线上)", "熊(等权指数在200日线下)"]])
    t["四段方向一致"] = sign.nunique(axis=1).eq(1).map({True: "是", False: ""})
    print(f"\n===== 最热档减最冷档：之后{H}天全A等权平均涨跌差")
    print(t.map(lambda x: f"{x:+.1%}" if isinstance(x, float) else x).to_string())
s.to_csv("sentiment_daily_ranked.csv")
