"""美股合约的“周末提前定价”：正股周末不交易，币安合约照常交易。

币安美股合约的指数价格（≈正股）在周一到周五连盘前、盘后、夜盘都在动（美东 20:00 到次日 04:00 有夜盘），
只有周末（美东周五 20:00 到周日 20:00）完全不动，此时只有合约在走，和港股夜里一样。
周日 20:00（北京时间周一 08:00 或 09:00）夜盘开盘，指数一次跳到真实价格。

这里看：周末合约涨跌了多少（W），夜盘开盘时正股实际跳了多少（J），之后合约是回落还是继续。
同一个周末所有美股基本同涨同跌，统计显著性按“周末”合并后再算。时间都用美东时间，夏令时自动处理。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/New_York"
US_SYMBOLS = ["SPYUSDT", "QQQUSDT", "IWMUSDT", "NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "METAUSDT", "MSFTUSDT", "AMZNUSDT",
              "GOOGLUSDT", "AVGOUSDT", "AMDUSDT", "NFLXUSDT", "ORCLUSDT", "INTCUSDT", "PLTRUSDT", "COINUSDT", "MSTRUSDT",
              "HOODUSDT", "CRCLUSDT", "BABAUSDT"]
# 周日开盘后的检查点：(标签, 相对周五的天数, 时刻)
AFTER = [("周日20:05", 2, "20:05"), ("周日20:30", 2, "20:30"), ("周日22:00", 2, "22:00"), ("周一00:00", 3, "00:00"),
         ("周一04:00", 3, "04:00"), ("周一09:29", 3, "09:29"), ("周一09:45", 3, "09:45"), ("周一12:00", 3, "12:00"),
         ("周一15:59", 3, "15:59")]


def weekend_table(df: pd.DataFrame) -> pd.DataFrame:
    """一个标的（hk.load 格式：close=合约，index=指数）每个周末一行。
    W = 合约周五 19:59 → 周日 19:59；J = 指数周五 19:59 → 周日 20:05（正股实际跳空）；
    a_* = 合约从周日 19:59 到各检查点。周日 20:05 指数没变的（遇周一假期等）跳过。"""
    et = df.index.tz_convert(TZ)
    pos = pd.Series(np.arange(len(df)), index=et.strftime("%Y-%m-%d %H:%M"))
    c, ix = df["close"].to_numpy(float), df["index"].to_numpy(float)

    def at(arr, day, off, hm):
        k = pos.get(f"{(day + pd.Timedelta(days=off)):%Y-%m-%d} {hm}")
        return arr[k] if k is not None else np.nan

    rows = []
    for fri in pd.DatetimeIndex(sorted(set(et.normalize()))):
        if fri.weekday() != 4:
            continue
        p0, i0 = at(c, fri, 0, "19:59"), at(ix, fri, 0, "19:59")
        p1, i1, i_open = at(c, fri, 2, "19:59"), at(ix, fri, 2, "19:59"), at(ix, fri, 2, "20:05")
        if not np.isfinite([p0, i0, p1, i_open]).all() or abs(i_open / i0 - 1) < 1e-6:
            continue
        r = {"symbol": df.attrs.get("symbol", ""), "fri": f"{fri:%Y-%m-%d}", "W": p1 / p0 - 1, "J": i_open / i0 - 1,
             "basis": p1 / i1 - 1 if np.isfinite(i1) else np.nan}
        for lab, off, hm in AFTER:
            r[lab] = at(c, fri, off, hm) / p1 - 1
        rows.append(r)
    return pd.DataFrame(rows)


def load_all(data_dir: Path, symbols=None) -> pd.DataFrame:
    from . import hk
    d = Path(data_dir)
    syms = symbols or sorted({p.name.split("_")[0] for p in d.glob("*_1m_index.csv")})
    parts = []
    for s in syms:
        if (d / f"{s}_1m_klines.csv").exists():
            parts.append(weekend_table(hk.load(s, d)))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _by_weekend(r: pd.Series, fri: pd.Series) -> dict:
    """每个周末先取平均（同一周末各标的高度相关），再看周末之间的平均、胜率和 t。"""
    w = r.groupby(fri).mean().dropna()
    n = len(w)
    sd = w.std(ddof=1) if n > 2 else np.nan
    return {"weekends": n, "wk_mean": w.mean(), "wk_win": (w > 0).mean(),
            "wk_t": w.mean() / sd * np.sqrt(n) if sd and sd > 0 else np.nan}


def rules(t: pd.DataFrame, cost_rt: float = 0.0014, ths=(0.005, 0.01, 0.02)) -> pd.DataFrame:
    """几条规则的扣费收益：周日 19:59（夜盘开盘前一分钟）按周末涨跌 反向/顺势 开仓，到各检查点平仓。
    对照：不管周末涨跌，一律做多（看周一整体漂移）。"""
    out = []
    labs = [a[0] for a in AFTER]
    for lab in labs:
        x = t[lab] - cost_rt
        out.append({"rule": "对照：每个周末都做多", "exit": lab, "n": int(x.notna().sum()), "mean": x.mean(),
                    "win": (x.dropna() > 0).mean(), **_by_weekend(x, t["fri"])})
    for th in ths:
        for name, side in (("反向", -1), ("顺势", 1)):
            m = t["W"].abs() > th
            g = t[m]
            s = side * np.sign(g["W"])
            for lab in labs:
                x = s * g[lab] - cost_rt
                out.append({"rule": f"周末合约涨跌 >{th:.1%}：{name}", "exit": lab, "n": int(x.notna().sum()),
                            "mean": x.mean(), "win": (x.dropna() > 0).mean(), **_by_weekend(x, g["fri"])})
    return pd.DataFrame(out)


def gap_fit(t: pd.DataFrame) -> dict:
    """正股实际跳空 J 对合约周末涨跌 W 的斜率：≈1 说明合约把周末定价定准了，<1 说明合约走过头。"""
    g = t.dropna(subset=["W", "J"])
    if len(g) < 10:
        return {}
    b = np.polyfit(g["W"], g["J"], 1)
    up, dn = g[g["W"] > 0.01], g[g["W"] < -0.01]
    return {"n": len(g), "slope": float(b[0]), "corr": float(g[["W", "J"]].corr().iloc[0, 1]),
            "up_W": up["W"].mean(), "up_J": up["J"].mean(), "dn_W": dn["W"].mean(), "dn_J": dn["J"].mean()}
