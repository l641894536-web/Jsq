"""个股面板：复权开高低收、成交量额、涨跌停、按时点股票池、开盘到开盘的收益标签。

所有矩阵均为 (交易日 n, 股票 m)，float32/bool。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ashare_lab.data.from_qlib import read_bin, read_calendar, read_membership

STOCK_RE = re.compile(r"^(SH6\d{5}|SZ0[0-3]\d{4}|SZ30[0-2]\d{3}|BJ[489]\d{5})$")


@dataclass
class Panel:
    dates: pd.DatetimeIndex
    codes: list[str]
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray
    A: np.ndarray
    limit: np.ndarray            # 当日涨跌幅限制（比例）
    in_univ: np.ndarray          # 中证全指成分（按时点）
    tier: np.ndarray             # 3=沪深300 2=中证500 1=中证1000 0=其余
    sector: np.ndarray           # (m,) 申万一级代码，未知为 ""
    age: np.ndarray              # 上市以来有价格的天数
    cache: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.dates)

    @property
    def m(self) -> int:
        return len(self.codes)

    # ------------------------------------------------------------ 衍生量（缓存）
    def get(self, key: str, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    @property
    def ret(self) -> np.ndarray:
        """收盘到收盘收益（相对上一个有效收盘）。"""
        def f():
            prev = pd.DataFrame(self.C).ffill().shift(1).to_numpy()
            with np.errstate(all="ignore"):
                r = self.C / prev - 1
            return r.astype(np.float32)
        return self.get("ret", f)

    @property
    def prev_close(self) -> np.ndarray:
        return self.get("prev_close", lambda: pd.DataFrame(self.C).ffill().shift(1).to_numpy(dtype=np.float32))

    def limit_hits(self, tol: float) -> dict[str, np.ndarray]:
        def f():
            pc = self.prev_close
            with np.errstate(all="ignore"):
                r = self.C / pc - 1
                ro = self.O / pc - 1
                lim = self.limit - tol
                close_hi = np.isclose(self.C, self.H, rtol=1e-5)
                close_lo = np.isclose(self.C, self.L, rtol=1e-5)
                return {
                    "up_close": (r >= lim) & close_hi,
                    "down_close": (r <= -lim) & close_lo,
                    "open_up": ro >= lim,
                    "open_down": ro <= -lim,
                }
        return self.get(f"limits_{tol}", f)

    def eligible(self, min_listed: int, tol: float) -> np.ndarray:
        """t 日可入选：中证全指成分、上市≥N日、当日有成交、t+1 开盘有价且未涨停。"""
        def f():
            hits = self.limit_hits(tol)
            nxt_open_ok = np.zeros_like(self.in_univ)
            nxt_open_ok[:-1] = np.isfinite(self.O[1:]) & ~hits["open_up"][1:]
            traded = np.isfinite(self.C) & (np.nan_to_num(self.V) > 0)
            return self.in_univ & (self.age >= min_listed) & traded & nxt_open_ok
        return self.get(f"elig_{min_listed}_{tol}", f)

    def label(self, h: int) -> np.ndarray:
        """t 日信号 → t+1 开盘买入、t+1+h 开盘卖出的复权收益。"""
        def f():
            y = np.full((self.n, self.m), np.nan, dtype=np.float32)
            with np.errstate(all="ignore"):
                y[: self.n - 1 - h] = self.O[1 + h:] / self.O[1:self.n - h] - 1
            return y
        return self.get(f"label_{h}", f)

    def exit_table(self, max_delay: int, tol: float) -> tuple[np.ndarray, np.ndarray]:
        """计划在 s 日开盘卖出时的实际成交价与是否顺延。

        s 日开盘跌停或停牌 → 顺延到之后第一个可卖的开盘（最多 max_delay 天）；仍卖不掉 →
        在 s+max_delay 日及以后第一个有开盘价的交易日按开盘价卖出；之后再无交易（退市/样本结束）→ 按最后收盘价计。
        """
        def f():
            n, m = self.n, self.m
            fin = np.isfinite(self.O)
            ok = fin & ~self.limit_hits(tol)["open_down"]
            nxt_ok = np.full((n + 1, m), n, dtype=np.int32)
            nxt_fin = np.full((n + 1, m), n, dtype=np.int32)
            for d in range(n - 1, -1, -1):
                nxt_ok[d] = np.where(ok[d], d, nxt_ok[d + 1])
                nxt_fin[d] = np.where(fin[d], d, nxt_fin[d + 1])
            s = np.arange(n)[:, None]
            e = nxt_ok[:n]
            late = e > s + max_delay
            e = np.where(late, nxt_fin[np.minimum(np.arange(n) + max_delay, n)], e)
            C = pd.DataFrame(self.C)
            last_close = C.ffill().iloc[-1].to_numpy(dtype=np.float32)
            Opad = np.vstack([self.O, last_close[None, :]])
            price = np.take_along_axis(Opad, e, axis=0).astype(np.float32)
            return price, (e > s)
        return self.get(f"exit_{max_delay}_{tol}", f)

    def trade_return(self, h: int, max_delay: int, tol: float) -> np.ndarray:
        """t 日信号 → t+1 开盘买入、计划 t+1+h 开盘卖出（含跌停/停牌顺延）的实际收益。"""
        def f():
            price, _ = self.exit_table(max_delay, tol)
            y = np.full((self.n, self.m), np.nan, dtype=np.float32)
            with np.errstate(all="ignore"):
                y[: self.n - 1 - h] = price[1 + h:] / self.O[1:self.n - h] - 1
            return y
        return self.get(f"tret_{h}_{max_delay}_{tol}", f)

    def drop_cache(self, keep=("ret", "prev_close", "limits_", "elig_", "label_", "exit_", "tret_", "df_", "tol")):
        for k in list(self.cache):
            if not k.startswith(keep):
                del self.cache[k]

    def period_mask(self, start, end) -> np.ndarray:
        d = self.dates
        return np.asarray((d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end)))


def board_limit(code: str, dates: pd.DatetimeIndex) -> np.ndarray:
    """各板块涨跌幅限制（不含 ST：股票池已通过中证全指成分排除 ST）。"""
    if code.startswith("688"):
        return np.full(len(dates), 0.20, dtype=np.float32)
    if code[:1] in "489" and not code.startswith(("600", "601", "603", "605")):
        return np.full(len(dates), 0.30, dtype=np.float32)
    if code.startswith(("300", "301", "302")):
        return np.where(dates >= pd.Timestamp("2020-08-24"), 0.20, 0.10).astype(np.float32)
    return np.full(len(dates), 0.10, dtype=np.float32)


def load_panel(qlib_dir: str | Path, start: str = "2010-01-01", industry_csv: str | Path | None = None,
               max_stocks: int | None = None, end: str | None = None, log=print) -> Panel:
    """end：截断日期。发现/验证阶段传入验证集最后一天，保证测试集数据根本不进入内存。"""
    q = Path(qlib_dir)
    cal_full = read_calendar(q)
    n_full = len(cal_full)
    keep = np.asarray(cal_full >= pd.Timestamp(start))
    if end is not None:
        keep &= np.asarray(cal_full <= pd.Timestamp(end))
    cal = cal_full[keep]
    inst = pd.read_csv(q / "instruments" / "all.txt", sep="\t", header=None, names=["sym", "s", "e"])
    syms = sorted(s for s in inst["sym"] if STOCK_RE.match(s))
    if end is not None:   # 截断日之前已上市的股票（all.txt 第二列为上市起始日）
        first = inst.set_index("sym")["s"]
        syms = [s for s in syms if pd.Timestamp(first[s]) <= pd.Timestamp(end)]
    if max_stocks:
        syms = syms[:max_stocks]
    codes = [s[2:] for s in syms]
    n, m = len(cal), len(syms)
    arrs = {k: np.full((n, m), np.nan, dtype=np.float32) for k in ("open", "high", "low", "close", "volume", "amount", "vwap")}
    for j, s in enumerate(syms):
        d = q / "features" / s.lower()
        for k in arrs:
            arrs[k][:, j] = read_bin(d / f"{k}.day.bin", n_full)[keep]
        if j % 1500 == 0:
            log(f"  读取 {j}/{m}")
    O, H, L, C, V, A, VW = (arrs[k] for k in ("open", "high", "low", "close", "volume", "amount", "vwap"))
    for x in (O, H, L, C):
        x[~(x > 0)] = np.nan
    A *= 1000.0  # 千元 → 元
    # 成交额校验（同 ashare_lab）：成交均价不在高低价之间 → 成交额置缺失
    with np.errstate(invalid="ignore"):
        bad = np.isfinite(VW) & np.isfinite(H) & np.isfinite(L) & ((VW > H * 1.05) | (VW < L * 0.95))
    A[bad] = np.nan
    A[~(A > 0)] = np.nan
    del VW
    limit = np.stack([board_limit(c, cal) for c in codes], axis=1)
    in_univ = read_membership(q, "csiall", cal, codes)
    in300 = read_membership(q, "csi300", cal, codes)
    in500 = read_membership(q, "csi500", cal, codes)
    in1000 = read_membership(q, "csi1000", cal, codes)
    tier = np.zeros((n, m), dtype=np.int8)
    tier[in1000] = 1
    tier[in500] = 2
    tier[in300] = 3
    age = np.cumsum(np.isfinite(C), axis=0).astype(np.int32)
    sector = np.array([""] * m, dtype=object)
    if industry_csv and Path(industry_csv).exists():
        ind = pd.read_csv(industry_csv, dtype={"code": str, "sector": str})
        mp = ind.drop_duplicates("code").set_index("code")["sector"]
        sector = np.array([mp.get(c, "") for c in codes], dtype=object)
    log(f"面板：{n} 日 × {m} 只；成交额校验剔除 {int(bad.sum())} 个股票日")
    return Panel(cal, codes, O, H, L, C, V, A, limit, in_univ, tier, sector, age)
