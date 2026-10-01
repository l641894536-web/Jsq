"""用 akshare 下载研究所需数据，整理成标准数据目录（见 market.py 顶部说明）。

需要能访问：swsresearch.com（申万指数）、eastmoney.com（指数/个股/国债/财报）。
个股数据量大（约 5000+ 只 × 10 年），默认不下载，加 --stocks 才下载，支持断点续传。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .market import INDEX_NAMES, SW1_NAMES

# 申万2021行业分类代码前两位 → 申万一级行业指数代码（fetch 时会用成分股接口抽样校验）
SW_PREFIX_TO_INDEX = {
    "11": "801010", "22": "801030", "23": "801040", "24": "801050", "27": "801080", "28": "801880",
    "33": "801110", "34": "801120", "35": "801130", "36": "801140", "37": "801150", "41": "801160",
    "42": "801170", "43": "801180", "45": "801200", "46": "801210", "48": "801780", "49": "801790",
    "51": "801230", "61": "801710", "62": "801720", "63": "801730", "64": "801890", "65": "801740",
    "71": "801750", "72": "801760", "73": "801770", "74": "801950", "75": "801960", "76": "801970",
    "77": "801980",
}

DEFAULT_INDICES = ["000985", "000300", "000905", "000852", "399303", "399370", "399371", "000922",
                   "000001", "399106", "399006"]


def _ak():
    try:
        import akshare as ak  # noqa: WPS433
    except ImportError as e:  # pragma: no cover
        raise SystemExit("需要安装 akshare：pip install -e '.[data]'") from e
    return ak


def retry(fn: Callable, *args, tries: int = 4, base_sleep: float = 2.0, log=print, **kwargs):
    for i in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — 网络接口的异常类型五花八门
            if i == tries - 1:
                raise
            wait = base_sleep * (2 ** i)
            log(f"  {getattr(fn, '__name__', fn)}{args} 失败：{e!r}，{wait:.0f}s 后重试")
            time.sleep(wait)


# ---------------------------------------------------------------- 规范化（可单测）
def normalize_sw_hist(df: pd.DataFrame, code: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]),
        "code": code,
        "name": SW1_NAMES.get(code, code),
        "close": pd.to_numeric(df["收盘"], errors="coerce"),
        "amount": pd.to_numeric(df["成交额"], errors="coerce"),
    })
    return out.dropna(subset=["date", "close"]).sort_values("date")


def normalize_index_hist(df: pd.DataFrame, code: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]),
        "code": code,
        "close": pd.to_numeric(df["收盘"], errors="coerce"),
        "amount": pd.to_numeric(df["成交额"], errors="coerce") if "成交额" in df else np.nan,
    })
    return out.dropna(subset=["date", "close"]).sort_values("date")


def normalize_bond(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]),
        "cn10y": pd.to_numeric(df["中国国债收益率10年"], errors="coerce"),
        "cn2y": pd.to_numeric(df["中国国债收益率2年"], errors="coerce"),
    })
    return out.dropna(subset=["date"]).sort_values("date").drop_duplicates("date")


def normalize_stock_hist(df: pd.DataFrame, code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "code", "close", "amount", "turnover"])
    return pd.DataFrame({
        "date": pd.to_datetime(df["日期"]),
        "code": code,
        "close": pd.to_numeric(df["收盘"], errors="coerce"),
        "amount": pd.to_numeric(df["成交额"], errors="coerce"),
        "turnover": pd.to_numeric(df["换手率"], errors="coerce"),
    }).dropna(subset=["date", "close"])


def normalize_industry_clf(df: pd.DataFrame) -> pd.DataFrame:
    code = df["symbol"].astype(str).str.extract(r"(\d{6})")[0]
    ind = df["industry_code"].astype(str).str.extract(r"(\d{6})")[0]
    out = pd.DataFrame({
        "code": code,
        "sector": ind.str[:2].map(SW_PREFIX_TO_INDEX),
        "start_date": pd.to_datetime(df["start_date"], errors="coerce"),
    })
    return out.dropna().sort_values(["code", "start_date"]).reset_index(drop=True)


def normalize_profit(df: pd.DataFrame, report_date: str) -> pd.DataFrame:
    return pd.DataFrame({
        "code": df["股票代码"].astype(str).str.zfill(6),
        "report_date": pd.Timestamp(report_date),
        "ann_date": pd.to_datetime(df["最新公告日期"], errors="coerce"),
        "net_profit": pd.to_numeric(df["净利润-净利润"], errors="coerce"),
    }).dropna(subset=["ann_date"])


# ---------------------------------------------------------------- 下载
def fetch_sectors(data_dir: Path, start: str, log=print, sleep: float = 0.5) -> pd.DataFrame:
    ak = _ak()
    frames = []
    for code, name in SW1_NAMES.items():
        log(f"申万一级 {code} {name}")
        try:
            df = retry(ak.index_hist_sw, symbol=code, period="day", log=log)
            frames.append(normalize_sw_hist(df, code))
        except Exception as e:  # noqa: BLE001
            log(f"  !! 申万接口失败（{e!r}），尝试东方财富接口")
            df = retry(ak.index_zh_a_hist, symbol=code, period="daily", start_date="19900101", end_date="20991231", log=log)
            out = normalize_index_hist(df, code)
            out["name"] = name
            frames.append(out[["date", "code", "name", "close", "amount"]])
        time.sleep(sleep)
    sec = pd.concat(frames, ignore_index=True)
    sec = sec[sec["date"] >= pd.Timestamp(start)]
    sec.to_csv(data_dir / "sector_daily.csv", index=False)
    log(f"写入 sector_daily.csv：{len(sec)} 行，{sec['date'].min().date()} ~ {sec['date'].max().date()}")
    return sec


def fetch_indices(data_dir: Path, start: str, codes: list[str] | None = None, log=print, sleep: float = 0.5) -> pd.DataFrame:
    ak = _ak()
    frames = []
    for code in codes or DEFAULT_INDICES:
        log(f"指数 {code} {INDEX_NAMES.get(code, '')}")
        try:
            df = retry(ak.index_zh_a_hist, symbol=code, period="daily",
                       start_date=pd.Timestamp(start).strftime("%Y%m%d"), end_date="20991231", log=log)
            frames.append(normalize_index_hist(df, code))
        except Exception as e:  # noqa: BLE001
            log(f"  !! 指数 {code} 下载失败，跳过：{e!r}")
        time.sleep(sleep)
    idx = pd.concat(frames, ignore_index=True)
    idx.to_csv(data_dir / "index_daily.csv", index=False)
    log(f"写入 index_daily.csv：{idx['code'].nunique()} 个指数")
    return idx


def fetch_macro(data_dir: Path, start: str, log=print) -> pd.DataFrame | None:
    ak = _ak()
    try:
        df = retry(ak.bond_zh_us_rate, start_date=pd.Timestamp(start).strftime("%Y%m%d"), log=log)
    except Exception as e:  # noqa: BLE001
        log(f"  !! 国债收益率下载失败，研究D将缺少利率类信号：{e!r}")
        return None
    m = normalize_bond(df)
    m = m[m["date"] >= pd.Timestamp(start)]
    m.to_csv(data_dir / "macro_daily.csv", index=False)
    log(f"写入 macro_daily.csv：{len(m)} 行")
    return m


def fetch_stock_industry(data_dir: Path, log=print) -> pd.DataFrame:
    ak = _ak()
    raw = retry(ak.stock_industry_clf_hist_sw, log=log)
    ind = normalize_industry_clf(raw)
    ind.to_csv(data_dir / "stock_industry.csv", index=False)
    log(f"写入 stock_industry.csv：{ind['code'].nunique()} 只股票的行业归属历史")
    # 抽样校验行业代码映射：最新归属 vs 申万成分股接口
    try:
        latest = ind.sort_values("start_date").groupby("code")["sector"].last()
        bad = []
        for code in list(SW1_NAMES)[:6]:
            comp = retry(ak.index_component_sw, symbol=code, log=log)
            members = comp["证券代码"].astype(str).str.extract(r"(\d{6})")[0].dropna()
            if len(members) == 0:
                continue
            hit = (latest.reindex(members) == code).mean()
            log(f"  校验 {code}{SW1_NAMES[code]}：成分股中映射一致的比例 {hit:.0%}")
            if hit < 0.9:
                bad.append(code)
        if bad:
            log(f"  !! 行业代码映射可能有误（{bad}），请检查 SW_PREFIX_TO_INDEX")
    except Exception as e:  # noqa: BLE001
        log(f"  （跳过映射校验：{e!r}）")
    return ind


def fetch_profit(data_dir: Path, start: str, log=print, sleep: float = 0.5) -> pd.DataFrame:
    ak = _ak()
    frames = []
    first_year = pd.Timestamp(start).year - 1
    today = pd.Timestamp.today()
    for y in range(first_year, today.year + 1):
        for md in ("0331", "0630", "0930", "1231"):
            rd = pd.Timestamp(f"{y}{md}")
            if rd > today:
                continue
            log(f"财报 {rd.date()}")
            try:
                df = retry(ak.stock_yjbb_em, date=rd.strftime("%Y%m%d"), log=log)
                frames.append(normalize_profit(df, rd.strftime("%Y-%m-%d")))
            except Exception as e:  # noqa: BLE001
                log(f"  !! {rd.date()} 财报下载失败：{e!r}")
            time.sleep(sleep)
    prof = pd.concat(frames, ignore_index=True)
    prof.to_csv(data_dir / "stock_profit.csv", index=False)
    log(f"写入 stock_profit.csv：{len(prof)} 行")
    return prof


def fetch_stock_daily(data_dir: Path, start: str, codes: list[str], log=print, sleep: float = 0.3) -> None:
    """逐只下载后复权日线，存到 data/raw/stocks/{code}.csv（已存在则跳过，可断点续传），最后合并。"""
    ak = _ak()
    raw = data_dir / "raw" / "stocks"
    raw.mkdir(parents=True, exist_ok=True)
    s = pd.Timestamp(start).strftime("%Y%m%d")
    for i, code in enumerate(codes):
        f = raw / f"{code}.csv"
        if f.exists():
            continue
        try:
            df = retry(ak.stock_zh_a_hist, symbol=code, period="daily", start_date=s, end_date="20991231",
                       adjust="hfq", tries=3, log=log)
            normalize_stock_hist(df, code).to_csv(f, index=False)
        except Exception as e:  # noqa: BLE001
            log(f"  !! {code} 失败：{e!r}")
            continue
        if i % 100 == 0:
            log(f"个股进度 {i}/{len(codes)}")
        time.sleep(sleep)
    consolidate_stocks(data_dir, log)


def consolidate_stocks(data_dir: Path, log=print) -> None:
    raw = data_dir / "raw" / "stocks"
    files = sorted(raw.glob("*.csv"))
    frames = [pd.read_csv(f, dtype={"code": str}) for f in files]
    frames = [f for f in frames if not f.empty]
    if not frames:
        log("没有个股数据可合并")
        return
    st = pd.concat(frames, ignore_index=True)
    st["code"] = st["code"].str.zfill(6)
    try:
        st.to_parquet(data_dir / "stock_daily.parquet", index=False)
        log(f"写入 stock_daily.parquet：{st['code'].nunique()} 只，{len(st)} 行")
    except Exception:  # noqa: BLE001 — 没装 pyarrow
        st.to_csv(data_dir / "stock_daily.csv", index=False)
        log(f"写入 stock_daily.csv：{st['code'].nunique()} 只，{len(st)} 行（建议安装 pyarrow）")


def stock_universe(data_dir: Path, log=print) -> list[str]:
    """当前上市 + 申万历史分类中出现过的股票（含已退市，缓解幸存者偏差）。"""
    ak = _ak()
    codes = set()
    try:
        cur = retry(ak.stock_info_a_code_name, log=log)
        codes |= set(cur["code"].astype(str).str.zfill(6))
    except Exception as e:  # noqa: BLE001
        log(f"  !! 获取当前A股列表失败：{e!r}")
    f = data_dir / "stock_industry.csv"
    if f.exists():
        codes |= set(pd.read_csv(f, dtype={"code": str})["code"].str.zfill(6))
    # 只保留沪深京 A 股代码段
    return sorted(c for c in codes if c[:1] in "0368" or c[:2] in ("43", "83", "87", "92"))


def fetch_all(data_dir: str | Path = "data", start: str = "2010-01-01", stocks: bool = False, log=print) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    fetch_sectors(data_dir, start, log)
    fetch_indices(data_dir, start, log=log)
    fetch_macro(data_dir, start, log)
    if stocks:
        fetch_stock_industry(data_dir, log)
        fetch_profit(data_dir, start, log)
        fetch_stock_daily(data_dir, start, stock_universe(data_dir, log), log)
    log("完成。下一步：python -m ashare_lab check && python -m ashare_lab run all")
