"""连亏减仓（都铎·琼斯：做得不顺就减量）在已验证规则上管不管用。
交易序列按平仓时间排：小时线突破（出场F=1R保本+跟踪3天低点）的黄金/白银/加密/AMD美光戴尔 牛市做多，加密熊市做多；美股跳空（币安有合约的，牛市）。
做法：A 连亏3笔后半仓，赚一笔恢复；B 连亏2笔后半仓；C 累计R低于最近10笔的均线时半仓（资金曲线过滤）。
看：合计R、最大回撤（R）、合计/回撤，前后两段。"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")

def apply_t(t, rule, ent="ts", ex="exit_ts", rc="r"):
    """按进场时间逐笔决定仓位；只用'进场前已经平仓'的单子算连亏（不偷看）"""
    t = t.sort_values(ent).reset_index(drop=True)
    done = t.sort_values(ex)[[ex, rc]].to_numpy()
    w = np.ones(len(t))
    for i, row in t.iterrows():
        past = done[done[:, 0] < row[ent]][:, 1].astype(float)
        if rule in ("A", "B"):
            k = 3 if rule == "A" else 2; streak = 0
            for x in past[::-1]:
                if x <= 0: streak += 1
                else: break
            w[i] = 0.5 if streak >= k else 1
        elif rule == "C" and len(past) >= 10:
            c = np.cumsum(past); w[i] = 0.5 if c[-1] < c[-10:].mean() else 1
    return t, w * t[rc].to_numpy()

def mdd(r):
    c = np.cumsum(r); return (c - np.maximum.accumulate(np.maximum(c, 0))).min()

def report(nm, t, rcol="r", ent="ts", tcol="exit_ts", mid=None):
    out = []
    for rule in ("全仓", "A", "B", "C"):
        tt, x = apply_t(t, "none" if rule == "全仓" else rule, ent, tcol, rcol)
        o = np.argsort(tt[tcol].to_numpy()); xs = x[o]          # 回撤按平仓顺序算
        h1 = x[(tt[ent] < mid).to_numpy()].sum(); h2 = x[(tt[ent] >= mid).to_numpy()].sum()
        out.append(f"{rule}: 合计 {x.sum():+6.1f}R 回撤 {mdd(xs):6.1f}R 比值 {x.sum()/abs(mdd(xs)) if mdd(xs) < 0 else np.nan:4.1f} (前 {h1:+.1f}/后 {h2:+.1f})")
    print(f"{nm}（{len(t)}笔）\n   " + "\n   ".join(out))

E = pd.read_csv("exit_trades.csv", parse_dates=["ts", "exit_ts"])
E = E[E.v == "F"]
mid = pd.Timestamp("2024-05-01", tz="UTC")
for g, env in (("黄金", "bull"), ("白银", "bull"), ("加密", "bull"), ("加密", "bear"), ("AMD/美光/戴尔", "bull")):
    report(f"{g} {'牛市' if env == 'bull' else '熊市'}突破做多", E[(E.grp == g) & (E.env == env) & (E.dir == "long")], mid=mid)
ep = pd.read_csv("ep_trades_bull8_x2_nextopen.csv", parse_dates=["date"])
ep["exit"] = ep.date + pd.to_timedelta(14, unit="D")   # 近似：破10日线平均拿约两周
EP2 = pd.read_csv("ep_trades_bull8_x2_nextopen.csv", parse_dates=["date"])
