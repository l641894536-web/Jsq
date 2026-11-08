"""生成工作台"市场环境"页用的 env.json（数据截至最近一个收盘日）。"""
import sys, json, os
sys.path.insert(0, "/home/claude/bt"); sys.path.insert(0, "/home/claude/src/Jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np, pandas as pd
import bear
from market_data import load

def r(x, n=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)

# ---------- A股
s = pd.read_csv("sentiment_temp.csv", index_col=0, parse_dates=True)
s["ma200"] = s["等权指数"].rolling(200).mean()
last = s.index[-1]; L = s.loc[last]
band = lambda t: "冰点" if t < 20 else "偏冷" if t < 40 else "中性" if t <= 60 else "偏热" if t <= 80 else "过热"
reg_today = "牛市" if L["等权指数"] > L["ma200"] else "熊市"
recent = s.loc[s.index[-10]:]
a_today = dict(date=str(last.date()), regime=reg_today, ew_vs_ma200=r(L["等权指数"] / L["ma200"] - 1, 4),
               temp=r(L["温度"], 1), band=band(L["温度"]), temp_min10=r(recent["温度"].min(), 1),
               temp_min10_date=str(recent["温度"].idxmin().date()), amount=r(L["成交额亿"], 0), heat=r(L["成交额热度"], 2),
               zt=int(L["涨停"]), dt=int(L["跌停"]), lb=int(L["连板高度"]), adv=r(L["上涨占比"], 3))
w = s.loc["2016-01-01":].dropna(subset=["温度", "fwd60"]).copy()
w["档"] = pd.cut(w["温度"], [-1, 20, 40, 60, 80, 101], labels=["冰点", "偏冷", "中性", "偏热", "过热"])
w["reg"] = w["牛熊"].astype(str).str[:1].map({"牛": "牛市", "熊": "熊市"})
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

# ---------- 美股
n = bear.frame("^NDX"); sp = bear.frame("^GSPC")
vix = n["vix"]
nl, sl = n.iloc[-1], sp.iloc[-1]
ndx_below = nl.px < nl.ma200
us_state = ("熊市" if ndx_below else "牛市") + ("·恐慌" if nl.vix >= 20 else "·平静")
br = bear.breaks(n); t0 = br[-1]
break_close = n.px.iloc[t0]
us_today = dict(date=str(n.index[-1].date()), state=us_state, ndx=r(nl.px, 1), ndx_ma200=r(nl.ma200, 1),
                ndx_vs=r(nl.px / nl.ma200 - 1, 4), ndx_dd52=r(nl.px / nl.hi252 - 1, 4), spx=r(sl.px, 1), spx_ma200=r(sl.ma200, 1),
                spx_vs=r(sl.px / sl.ma200 - 1, 4), vix=r(nl.vix, 2), break_date=str(n.index[t0].date()), break_close=r(break_close, 1),
                stop_line=r(break_close * 0.85, 0))
nser = n.iloc[-500:]
us_series = [dict(d=str(i.date()), ndx=r(v.px, 1), ma=r(v.ma200, 1), vix=r(v.vix, 2)) for i, v in nser.iterrows()]

findings = [
    dict(m="美股合约", rule="纳指在200日线上方时，不做空", ev="AMD/美光/Dell 和另外25只科技股、近5年小时线，8组测试里牛市做空全部亏钱；去掉后8组全部改善、回撤变小", lvl="高", note="牛转熊拐点附近会失灵（如2022年初）"),
    dict(m="美股合约", rule="纳指在200日线下方时，少做、轻仓", ev="熊市里做多做空都没有稳定优势：2022年长熊做空赚，2025年短暂恐慌做多赚", lvl="中", note=""),
    dict(m="合约", rule="浮盈到1倍止损距离后，止损挪到开仓价", ev="盈利变亏损从30%–41%降到8%–13%；总收益在扩大样本里有高有低", lvl="高", note="控制回吐用，不是多赚钱的规则"),
    dict(m="美股指数", rule="跌破200日线后，约八成一年内更高；长熊提前分不出来", ev="纳指1990年以来29次跌破，24次半年后更高；到第20/40天的价格、均线、VIX都分不出长熊", lvl="中", note="只有9次的线索：纳指跌破而标普没破时，9次全部收复"),
    dict(m="美股指数", rule="认错线：跌破日收盘再跌15%，按长熊处理", ev="纳指最坏一年从−52%变−22%，平均收益不变；标普最坏从−37%变−17%", lvl="中", note="卖错过1990年（纳指）、2020年（标普）"),
    dict(m="A股大盘", rule="情绪冰点（温度<20）分批买，过热（>80）不追", ev="2016年以来：冰点之后60天平均+4.1%，过热−2.0%；有对比的10年里9年过热比冰点差；熊市冰点17段里11段60天后更高", lvl="中", note="冰点第一天买常常还要再跌10%–28%，要分批"),
    dict(m="A股大盘", rule="熊市里情绪突然过热，多数是反弹陷阱", ev="熊市过热8段里5段之后下跌", lvl="低", note="2019年2月、2024年9月这两次是新行情的起点，事先分不出"),
    dict(m="A股个股", rule="不追放量新高；熊市偏冷时不做突破、金叉", ev="放量突破60日新高之后20天平均跑输全A 1.4%–1.8%；突破、金叉在熊市偏冷时前后两段、科技股和全A都跑输", lvl="中", note="突破类形态能提高大涨概率（约1.2–1.3倍），但平均收益更差"),
    dict(m="A股个股", rule="牛市里情绪偏冷时，买上升趋势中回踩20日线的股票", ev="之后20天跑赢全A：科技股+1.7%，全A+0.8%；前后两段都为正", lvl="低", note="36个组合里唯一过关的，可能有运气，需样本外验证"),
    dict(m="A股个股", rule="深跌股票整体跑输大盘；熊市里情绪偏热时别抄底", ev="跌到一年高点70%以下，之后60天在每种环境都跑输全A；熊市偏热时绝对收益约−3%", lvl="中", note=""),
]
env = dict(asof=a_today["date"], a=dict(today=a_today, stats=stats, series=a_series), us=dict(today=us_today, series=us_series), findings=findings)
json.dump(env, open("/home/claude/wb/env.json", "w"), ensure_ascii=False, separators=(",", ":"))
print(json.dumps(dict(a=a_today, us=us_today), ensure_ascii=False, indent=1)); print(pd.DataFrame(stats).to_string())
print(os.path.getsize("/home/claude/wb/env.json"))
