"""把 ashare_gap_bt.py / ashare_cycle_bt.py 的结果整理成 env_static.json 的 gap_research（页面"A股短线情绪"和查个股"开盘习惯"用）。
先跑那两个脚本（生成 _gap_up.pkl/_gap_dn.pkl/_cycle_s.pkl），再跑这个，输出 /tmp/gap_research.json；trans5、mkt 两块按 ashare_cycle_bt.py 打印的结果手填。"""
import json, numpy as np, pandas as pd
FU = pd.read_pickle("/home/claude/bt/_gap_up.pkl"); FD = pd.read_pickle("/home/claude/bt/_gap_dn.pkl"); s = pd.read_pickle("/home/claude/bt/_cycle_s.pkl")
r = lambda v, n=4: None if v is None or not np.isfinite(v) else round(float(v), n)
cat = {}
for (b, q), x in FU.groupby(["板块", "波动"]):
    y = FD[(FD.板块 == b) & (FD.波动 == q)]
    cat[f"{b}|{int(q)}"] = dict(up_n=len(x), up_fade=r((x.oc < 0).mean(), 3), up_x=r(x.ocx.mean()), up_oc=r(x.oc.mean()),
                                up_h=[r(x[x.per == "前半"].ocx.mean()), r(x[x.per == "后半"].ocx.mean())],
                                dn_n=len(y), dn_rise=r((y.oc > 0).mean(), 3), dn_x=r(y.ocx.mean()), dn_oc=r(y.oc.mean()),
                                dn_h=[r(y[y.per == "前半"].ocx.mean()), r(y[y.per == "后半"].ocx.mean())])
zt = {}
for lab in ["昨天首板", "昨天连板"]:
    x = FU[FU.昨天 == lab]; y = FD[FD.昨天 == lab]
    zt[lab] = dict(up_n=len(x), up_fade=r((x.oc < 0).mean(), 3), up_x=r(x.ocx.mean()), up_oc=r(x.oc.mean()), dn_n=len(y), dn_x=r(y.ocx.mean()), dn_oc=r(y.oc.mean()))
ORDER = ["冰点", "低位回升", "中高位升温", "高潮", "中高位退潮", "低位回落"]
w = s[s["期"].isin(["前半", "后半"])].dropna(subset=["阶段"]); o = s[s["期"] == "2016-21"].dropna(subset=["阶段"])
ph = {}
for p in ORDER:
    x = w[w.阶段 == p]; x1 = x[x.期 == "前半"]; x2 = x[x.期 == "后半"]; z = o[o.阶段 == p]
    ph[p] = dict(days=len(x), share=r(len(x) / len(w), 3), hi_x=r(x.hi_x1.mean()), lo_x=r(x.lo_x1.mean()), hi_fade=r(x.hi_fade1.mean(), 3),
                 zt_gap=r(x.zt_gap1.mean()), zt_oc=r(x.zt_oc1.mean()), zt_oc_h=[r(x1.zt_oc1.mean()), r(x2.zt_oc1.mean()), r(z.zt_oc1.mean())],
                 f5=r(x.f5.mean()), f20=r(x.f20.mean()), f20_up=r((x.f20.dropna() > 0).mean(), 3), f20_h=[r(x1.f20.mean()), r(x2.f20.mean()), r(z.f20.mean())])
allx = dict(up_n=len(FU), up_fade=r((FU.oc < 0).mean(), 3), up_x=r(FU.ocx.mean()), up_oc=r(FU.oc.mean()), up_med=r(FU.oc.median()),
            dn_n=len(FD), dn_rise=r((FD.oc > 0).mean(), 3), dn_x=r(FD.ocx.mean()), dn_oc=r(FD.oc.mean()), dn_med=r(FD.oc.median()))
json.dump(dict(period="2021-11~2026-11", cat=cat, zt=zt, phase=ph, all=allx,
               note="research/ashare_gap_bt.py、research/ashare_cycle_bt.py"), open("/tmp/gap_research.json", "w"), ensure_ascii=False)
