import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
import turtle_bt as TB
res, D = pickle.load(open("/home/claude/bt/turtle_res.pkl", "rb"))
for L in (40, 70, 100):
    for x in (20, 30):
        d2 = {}
        for s, d in D.items():
            d = d.copy(); d[f"hi{L}"] = d.high.rolling(L).max().shift(1); d[f"lo{L}"] = d.low.rolling(L).min().shift(1)
            d[f"lo{x}"] = d.low.rolling(x).min().shift(1); d[f"hi{x}"] = d.high.rolling(x).max().shift(1); d2[s] = d
        C, T = TB.run(d2, L, x, "regime_long", risk=0.005); s = TB.stats(C); h = TB.halves(C)
        print(f"进{L}日/出{x}日: 年化 {s['cagr']*100:+.1f}% 回撤 {s['mdd']*100:.1f}% 前段 {h[0]*100:+.1f}% 后段 {h[1]*100:+.1f}% {len(T)}笔")
C, T = TB.run(D, 55, 20, "regime_long", risk=0.005, max_units=1); s = TB.stats(C); h = TB.halves(C)
print(f"不加仓(只1个单位，风险0.5%/N): 年化 {s['cagr']*100:+.1f}% 回撤 {s['mdd']*100:.1f}% 前段 {h[0]*100:+.1f}% 后段 {h[1]*100:+.1f}%")
C, T = TB.run(D, 55, 20, "regime_long", risk=0.01, max_units=1); s = TB.stats(C); h = TB.halves(C)
print(f"不加仓(只1个单位，风险1%/N): 年化 {s['cagr']*100:+.1f}% 回撤 {s['mdd']*100:.1f}% 前段 {h[0]*100:+.1f}% 后段 {h[1]*100:+.1f}%")
TB.FUND = 0.0006
C, T = TB.run(D, 55, 20, "regime_long", risk=0.005); s = TB.stats(C); h = TB.halves(C)
print(f"资金费翻倍(0.06%/天): 年化 {s['cagr']*100:+.1f}% 回撤 {s['mdd']*100:.1f}% 前段 {h[0]*100:+.1f}% 后段 {h[1]*100:+.1f}%")
TB.FUND = 0.0003
for nm, ss in {"去掉币": [s for s in D if TB.GROUP[s] != "crypto"], "只有币": [s for s in D if TB.GROUP[s] == "crypto"],
               "只有金属": ["XAU", "XAG", "XPT", "XPD", "COPPER"], "去掉黄金": [s for s in D if s != "XAU"], "去掉金银": [s for s in D if s not in ("XAU", "XAG")],
               "币安上最常见的8个(金银+BTC/ETH/SOL+QQQ/SPY+铜)": ["XAU", "XAG", "BTC", "ETH", "SOL", "QQQ", "SPY", "COPPER"]}.items():
    C, T = TB.run(D, 55, 20, "regime_long", risk=0.005, syms=ss); s = TB.stats(C); h = TB.halves(C)
    print(f"{nm}: 年化 {s['cagr']*100:+.1f}% 回撤 {s['mdd']*100:.1f}% 前段 {h[0]*100:+.1f}% 后段 {h[1]*100:+.1f}% {len(T)}笔")
