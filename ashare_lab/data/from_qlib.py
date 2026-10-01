"""把 qlib 格式的A股日线（如 chenditc/investment_data 的 GitHub Release）转换成标准数据目录。

适用场景：访问不了申万/东方财富接口，但能访问 GitHub 时。
    wget https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz
    tar -zxf qlib_bin.tar.gz -C ~/qlib_cn --strip-components=1
    python -m ashare_lab import-qlib ~/qlib_cn --industry data/stock_industry_static.csv

qlib 数据只有个股量价（含已退市股票）和几个中证指数，没有行业、市值、财报，所以：
- 行业：由 `industry_static.py` 生成的“个股→申万一级”静态映射（非点对点，见其说明）；
- 行业指数：成分股日收益按“过去 250 日平均成交额”加权（t-1 日权重）合成；
  市场基准 ALLA 用同样方法由全部已分类个股合成，保证相对强弱的口径一致；
- 市值分层：用中证指数成分（按时点）代替——沪深300=龙头，中证500/1000=二线，其余=尾部（小微盘/ST/次新）；
- 风格：成长（TMT+电新+军工+医药）/ 价值（银行+非银+地产+煤炭+石化+公用+交运+钢铁+建筑）行业组合；
- 成交占比分母：全部个股（含未分类）成交额之和，写入 market_amount.csv。
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

QLIB_INDEX = {"SH000300": "000300", "SH000905": "000905", "SH000906": "000906", "SH000852": "000852", "SH000985": "000985"}
# 注意排除 SZ399xxx（深交所发布的指数，如 399300）
STOCK_RE = re.compile(r"^(SH6\d{5}|SZ0[0-3]\d{4}|SZ30[0-2]\d{3}|BJ[489]\d{5})$")

GROWTH_SECTORS = ["801080", "801750", "801770", "801760", "801730", "801740", "801150"]
VALUE_SECTORS = ["801780", "801790", "801180", "801950", "801960", "801160", "801170", "801040", "801720"]


def read_calendar(qdir: Path) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.read_csv(qdir / "calendars" / "day.txt", header=None)[0])


def read_bin(path: Path, n_cal: int) -> np.ndarray:
    """qlib .bin：float32 小端，第一个数是起始日在日历中的下标。返回与日历等长的数组。"""
    out = np.full(n_cal, np.nan, dtype=np.float32)
    if not path.exists():
        return out
    a = np.fromfile(path, dtype="<f4")
    if len(a) < 2:
        return out
    start = int(a[0])
    vals = a[1:]
    end = min(n_cal, start + len(vals))
    out[start:end] = vals[: end - start]
    return out


def read_membership(qdir: Path, name: str, cal: pd.DatetimeIndex, codes: list[str]) -> np.ndarray:
    """指数成分（按时点）→ 日期×股票 的布尔矩阵。"""
    col = {c: i for i, c in enumerate(codes)}
    m = np.zeros((len(cal), len(codes)), dtype=bool)
    f = qdir / "instruments" / f"{name}.txt"
    if not f.exists():
        return m
    df = pd.read_csv(f, sep="\t", header=None, names=["sym", "start", "end"])
    for sym, s, e in df.itertuples(index=False):
        j = col.get(sym[2:])
        if j is None:
            continue
        a = cal.searchsorted(pd.Timestamp(s))
        b = cal.searchsorted(pd.Timestamp(e), side="right")
        m[a:b, j] = True
    return m


def weighted_index(ret: np.ndarray, w: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """按权重合成日收益：只用当日收益与权重都有效的股票。"""
    r = ret[:, cols]
    ww = w[:, cols]
    ok = np.isfinite(r) & np.isfinite(ww) & (ww > 0)
    num = np.where(ok, r * ww, 0.0).sum(axis=1)
    den = np.where(ok, ww, 0.0).sum(axis=1)
    with np.errstate(all="ignore"):
        out = num / den
    return np.where(den > 0, out, np.nan)


def build_standard_dir(qdir: str | Path, industry_csv: str | Path, out_dir: str | Path,
                       start: str = "2010-01-01", stock_start: str = "2012-01-01", weighting: str = "liquidity",
                       scheme: str = "sw1", groups_sw1: dict | None = None, min_members: int = 10,
                       log=print) -> Path:
    """weighting: "liquidity"（过去250日平均成交额加权，默认）或 "equal"（等权，用于稳健性检验）。

    scheme: "sw1"（申万一级 31 个行业）或 "em"（东方财富 86 个细分行业，成分股少于 min_members 的不参与）。
    em 口径下会另写 groups.json（主题组合→细分行业代码）和 sector_parent.json（细分行业→申万一级）。
    """
    qdir, out = Path(qdir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cal_full = read_calendar(qdir)
    n_full = len(cal_full)
    keep = np.asarray(cal_full >= pd.Timestamp(start))
    cal = cal_full[keep]
    inst = pd.read_csv(qdir / "instruments" / "all.txt", sep="\t", header=None, names=["sym", "s", "e"])
    stocks = sorted(s for s in inst["sym"] if STOCK_RE.match(s))
    codes = [s[2:] for s in stocks]
    log(f"qlib 日历 {cal_full[0].date()} ~ {cal_full[-1].date()}；个股 {len(stocks)} 只；截取 {cal[0].date()} 起 {len(cal)} 日")

    # ---- 个股矩阵 ----
    n, m = len(cal), len(stocks)
    close = np.full((n, m), np.nan, dtype=np.float32)
    amount = np.full((n, m), np.nan, dtype=np.float32)
    for j, s in enumerate(stocks):
        d = qdir / "features" / s.lower()
        close[:, j] = read_bin(d / "close.day.bin", n_full)[keep]
        amount[:, j] = read_bin(d / "amount.day.bin", n_full)[keep] * 1000.0  # 千元 → 元
        if j % 1000 == 0:
            log(f"  读取个股 {j}/{m}")
    close[close <= 0] = np.nan
    amount[~(amount > 0)] = np.nan
    # 数据校验：成交均价(vwap = 成交额/成交量) 必须落在当日 [最低, 最高] 之间，否则成交额有误（如单位错误）
    bad_cnt = 0
    for j, s in enumerate(stocks):
        d = qdir / "features" / s.lower()
        vw = read_bin(d / "vwap.day.bin", n_full)[keep]
        hi = read_bin(d / "high.day.bin", n_full)[keep]
        lo = read_bin(d / "low.day.bin", n_full)[keep]
        with np.errstate(invalid="ignore"):
            bad = np.isfinite(vw) & np.isfinite(hi) & np.isfinite(lo) & ((vw > hi * 1.05) | (vw < lo * 0.95))
        if bad.any():
            amount[bad, j] = np.nan
            bad_cnt += int(bad.sum())
    log(f"  成交额校验：{bad_cnt} 个股票日的成交均价不在当日高低价之间，成交额置为缺失")

    # 日收益：相对上一个有效收盘（停牌复牌也计入），上市前 5 个交易日不计，±35% 截断
    cdf = pd.DataFrame(close)
    prev = cdf.ffill().shift(1)
    ret = (cdf / prev - 1).to_numpy(dtype=np.float32, copy=True)
    age = cdf.notna().cumsum().to_numpy()
    ret[(age <= 5) | ~np.isfinite(close)] = np.nan
    ret = np.clip(ret, -0.35, 0.35)

    # 权重：过去 250 日平均成交额（至少 60 日），用 t-1 日的值
    liq = pd.DataFrame(amount).rolling(250, min_periods=60).mean().shift(1).to_numpy(dtype=np.float32)
    if weighting == "equal":
        liq = np.where(np.isfinite(liq), 1.0, np.nan).astype(np.float32)
    log(f"  行业/组合指数加权方式：{weighting}")

    # ---- 行业映射 ----
    ind = pd.read_csv(industry_csv, dtype={"code": str, "sector": str})
    ind["code"] = ind["code"].str.zfill(6)
    sec_of = ind.drop_duplicates("code", keep="last").set_index("code")["sector"]
    sw1 = np.array([sec_of.get(c, "") for c in codes], dtype=object)
    from .market import SW1_NAMES
    sector_names = dict(SW1_NAMES)
    sector = sw1
    if scheme == "em":
        import json

        from .industry_static import EM_TO_SW1
        if "em_industry" not in ind:
            raise ValueError("em 口径需要行业映射里有 em_industry 列（重新生成 stock_industry_static.csv）")
        em_of = ind.dropna(subset=["em_industry"]).drop_duplicates("code", keep="last").set_index("code")["em_industry"]
        em_name = np.array([em_of.get(c, "") for c in codes], dtype=object)
        all_names = sorted(set(em_name) - {""})
        code_of = {nm: f"EM{i + 1:02d}" for i, nm in enumerate(all_names)}
        kept = [nm for nm in all_names if (em_name == nm).sum() >= min_members]
        dropped = sorted(set(all_names) - set(kept))
        if dropped:
            log(f"  成分股少于 {min_members} 只、不参与的细分行业：{dropped}")
        sector = np.array([code_of[nm] if nm in kept else "" for nm in em_name], dtype=object)
        sector_names = {code_of[nm]: nm for nm in kept}
        parent = {code_of[nm]: EM_TO_SW1[nm] for nm in kept if nm in EM_TO_SW1}
        groups_out = {g: sorted(c for c, p in parent.items() if p in set(members)) for g, members in (groups_sw1 or {}).items()}
        (out / "groups.json").write_text(json.dumps(groups_out, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "sector_parent.json").write_text(json.dumps(parent, ensure_ascii=False, indent=1), encoding="utf-8")
    sectors = sorted(s for s in set(sector) if s)
    tot_amt = np.nansum(amount, axis=1)
    mapped_amt = np.nansum(np.where(sector != "", amount, np.nan), axis=1)
    cov = pd.Series(mapped_amt / np.where(tot_amt > 0, tot_amt, np.nan), index=cal)
    log("  已分类个股成交额覆盖率（按年均值）：" + "，".join(f"{y}:{v:.0%}" for y, v in cov.groupby(cov.index.year).mean().items()))

    # ---- 行业日线 ----
    sec_rows = []
    for sc in sectors:
        cols = np.flatnonzero(sector == sc)
        r = weighted_index(ret, liq, cols)
        lvl = 1000 * np.cumprod(1 + np.nan_to_num(r, nan=0.0))
        amt = np.nansum(amount[:, cols], axis=1)
        sec_rows.append(pd.DataFrame({"date": cal, "code": sc, "name": sector_names.get(sc, sc), "close": lvl, "amount": amt}))
    sec_df = pd.concat(sec_rows, ignore_index=True)
    sec_df.to_csv(out / "sector_daily.csv", index=False)
    pd.DataFrame({"date": cal, "amount": tot_amt}).to_csv(out / "market_amount.csv", index=False)
    cov.rename("coverage").rename_axis("date").reset_index().to_csv(out / "industry_coverage.csv", index=False)
    log(f"  写入 sector_daily.csv：{len(sectors)} 个行业（口径 {scheme}）")

    # ---- 指数 ----
    idx_rows = []
    for sym, code in QLIB_INDEX.items():
        d = qdir / "features" / sym.lower()
        if not d.exists():
            continue
        c = read_bin(d / "close.day.bin", n_full)[keep]
        a = read_bin(d / "amount.day.bin", n_full)[keep] * 1000.0
        idx_rows.append(pd.DataFrame({"date": cal, "code": code, "close": c, "amount": a}))
    mapped = np.flatnonzero(sw1 != "")

    def add(code, cols, weights=liq):
        r = weighted_index(ret, weights, cols)
        idx_rows.append(pd.DataFrame({"date": cal, "code": code,
                                      "close": 1000 * np.cumprod(1 + np.nan_to_num(r, nan=0.0)),
                                      "amount": np.nansum(amount[:, cols], axis=1)}))

    add("ALLA", mapped)
    add("GROWTH", np.flatnonzero(np.isin(sw1, GROWTH_SECTORS)))
    add("VALUE", np.flatnonzero(np.isin(sw1, VALUE_SECTORS)))
    in300 = read_membership(qdir, "csi300", cal, codes)
    in500 = read_membership(qdir, "csi500", cal, codes)
    in1000 = read_membership(qdir, "csi1000", cal, codes)
    micro = ~(in300 | in500 | in1000)
    eq = np.where(np.isfinite(liq), 1.0, np.nan).astype(np.float32)
    r_micro = weighted_index(ret, np.where(micro, eq, np.nan), np.arange(m))
    idx_rows.append(pd.DataFrame({"date": cal, "code": "MICRO",
                                  "close": 1000 * np.cumprod(1 + np.nan_to_num(r_micro, nan=0.0)),
                                  "amount": np.nansum(np.where(micro, amount, np.nan), axis=1)}))
    idx = pd.concat(idx_rows, ignore_index=True).dropna(subset=["close"])
    idx.to_csv(out / "index_daily.csv", index=False)
    log(f"  写入 index_daily.csv：{idx['code'].nunique()} 个指数")

    # ---- 个股长表（研究E / 成交集中度）----
    s0 = int(cal.searchsorted(pd.Timestamp(stock_start)))
    tier = np.full((n, m), "尾部", dtype=object)
    tier[in500 | in1000] = "二线"
    tier[in300] = "龙头"
    frames = []
    for j in range(m):
        c = close[s0:, j]
        ok = np.isfinite(c)
        if not ok.any():
            continue
        frames.append(pd.DataFrame({"date": cal[s0:][ok], "code": codes[j], "close": c[ok],
                                    "amount": amount[s0:, j][ok], "tier": tier[s0:, j][ok]}))
    st = pd.concat(frames, ignore_index=True)
    st["code"] = st["code"].astype("category")
    st["tier"] = st["tier"].astype("category")
    try:
        st.to_parquet(out / "stock_daily.parquet", index=False)
    except Exception:  # noqa: BLE001
        st.to_csv(out / "stock_daily.csv", index=False)
    pd.DataFrame({"code": codes, "sector": sector, "start_date": "2000-01-01"}).query("sector != ''") \
        .to_csv(out / "stock_industry.csv", index=False)
    log(f"  写入个股 {st['code'].nunique()} 只、{len(st)} 行（{cal[s0].date()} 起）")
    return out
