"""研究用的统一数据容器 + 从标准 CSV/Parquet 目录加载。

标准数据目录（data/）约定——任何数据源（akshare / Wind / Choice / Tushare）
只要整理成下面的格式就能直接跑全部研究：

必需：
  sector_daily.csv   date, code, name, close, amount           行业指数日线（申万一级）
  index_daily.csv    date, code, close[, amount]                市场基准、风格指数、小盘/红利指数
可选：
  macro_daily.csv    date, cn10y, cn2y, ...                     国债收益率等（研究D）
  stock_daily.parquet  date, code, close, amount, turnover      个股日线，close 为后复权价，turnover 为换手率%（研究B集中度、研究E）
  stock_industry.csv code, sector, start_date                   个股所属申万一级行业（带生效日期，点对点）
  stock_profit.csv   code, report_date, ann_date, net_profit    财报净利润与公告日（判断亏损股，按公告日生效）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

SW1_NAMES = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}

INDEX_NAMES = {
    "000985": "中证全指", "000300": "沪深300", "000905": "中证500", "000852": "中证1000",
    "399303": "国证2000", "399370": "国证成长", "399371": "国证价值", "000922": "中证红利",
    "000001": "上证指数", "399106": "深证综指", "000918": "300成长", "000919": "300价值",
    "399006": "创业板指", "000688": "科创50", "000906": "中证800",
    "ALLA": "全A合成", "GROWTH": "成长组合", "VALUE": "价值组合", "MICRO": "小微盘",
}


@dataclass
class MarketData:
    sector_close: pd.DataFrame
    sector_amount: pd.DataFrame
    sector_names: dict[str, str]
    market_close: pd.Series
    total_amount: pd.Series
    index_close: pd.DataFrame
    index_amount: pd.DataFrame
    groups: dict[str, list[str]]
    macro: pd.DataFrame | None = None
    stocks: pd.DataFrame | None = None           # long: date, code, close, amount, turnover
    stock_industry: pd.DataFrame | None = None   # code, sector, start_date
    stock_profit: pd.DataFrame | None = None     # code, report_date, ann_date, net_profit
    source: str = "csv"
    notes: list[str] = field(default_factory=list)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.sector_close.index

    @property
    def is_synthetic(self) -> bool:
        return self.source == "synthetic"

    def name(self, code: str) -> str:
        return self.sector_names.get(code) or INDEX_NAMES.get(code) or code

    def valid_groups(self) -> dict[str, list[str]]:
        cols = set(self.sector_close.columns)
        out = {}
        for g, members in self.groups.items():
            m = [c for c in members if c in cols]
            if m:
                out[g] = m
        return out

    def group_close(self, members: list[str]) -> pd.Series:
        """主题组合指数：成员行业日收益等权合成（可解释、无需市值数据）。"""
        from ..core.returns import index_from_returns
        rets = self.sector_close[members].pct_change(fill_method=None)
        return index_from_returns(rets)

    def group_amount(self, members: list[str]) -> pd.Series:
        return self.sector_amount[members].sum(axis=1, min_count=len(members))

    def turnover_share(self) -> pd.DataFrame:
        return self.sector_amount.div(self.total_amount, axis=0)

    def to_csv_dir(self, data_dir: str | Path) -> Path:
        """按标准数据目录格式导出（便于检查、或把其他来源的数据整理成统一格式）。"""
        d = Path(data_dir)
        d.mkdir(parents=True, exist_ok=True)
        sec = self.sector_close.stack().rename("close").to_frame()
        sec["amount"] = self.sector_amount.stack()
        sec = sec.reset_index()
        sec.columns = ["date", "code", "close", "amount"]
        sec["name"] = sec["code"].map(self.sector_names)
        sec.to_csv(d / "sector_daily.csv", index=False)
        idx = self.index_close.stack().rename("close").to_frame()
        idx["amount"] = self.index_amount.reindex_like(self.index_close).stack().reindex(idx.index)
        idx = idx.reset_index()
        idx.columns = ["date", "code", "close", "amount"]
        idx.to_csv(d / "index_daily.csv", index=False)
        if self.macro is not None:
            self.macro.rename_axis("date").reset_index().to_csv(d / "macro_daily.csv", index=False)
        if self.stocks is not None:
            self.stocks.to_csv(d / "stock_daily.csv", index=False)
        if self.stock_industry is not None:
            self.stock_industry.to_csv(d / "stock_industry.csv", index=False)
        if self.stock_profit is not None:
            self.stock_profit.to_csv(d / "stock_profit.csv", index=False)
        return d

    def summary(self) -> str:
        d = self.dates
        parts = [
            f"数据来源: {self.source}",
            f"区间: {d.min().date()} ~ {d.max().date()}（{len(d)} 个交易日）",
            f"行业数: {self.sector_close.shape[1]}",
            f"指数: {', '.join(f'{c}{self.name(c)}' for c in self.index_close.columns)}",
            f"宏观: {'有' if self.macro is not None else '无'}",
            f"个股: {self.stocks['code'].nunique() if self.stocks is not None else 0} 只",
        ]
        return "；".join(parts)


def _read_table(path: Path) -> pd.DataFrame | None:
    if path.exists():
        return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype={"code": str, "sector": str})
    return None


def _norm_code(s: pd.Series) -> pd.Series:
    """纯数字代码补齐 6 位（CSV 读入时可能丢了前导 0），其他代码原样保留。"""
    s = s.astype(str).str.strip()
    return s.where(~s.str.fullmatch(r"\d{1,6}"), s.str.zfill(6))


def _pivot(df: pd.DataFrame, value: str) -> pd.DataFrame:
    p = df.pivot_table(index="date", columns="code", values=value, aggfunc="last")
    p.columns = [str(c) for c in p.columns]
    return p.sort_index()


def load_csv_dir(data_dir: str | Path, cfg: dict) -> MarketData:
    data_dir = Path(data_dir)
    sec = _read_table(data_dir / "sector_daily.csv")
    if sec is None:
        raise FileNotFoundError(
            f"{data_dir}/sector_daily.csv 不存在。先运行 `python -m ashare_lab fetch` 下载数据，"
            "或者用 `--synthetic` 在合成数据上检查流程。"
        )
    sec["date"] = pd.to_datetime(sec["date"])
    sec["code"] = _norm_code(sec["code"])
    sector_close = _pivot(sec, "close")
    sector_amount = _pivot(sec, "amount").reindex_like(sector_close)
    names = dict(SW1_NAMES)
    if "name" in sec:
        names.update(sec.dropna(subset=["name"]).groupby("code")["name"].last().to_dict())

    idx = _read_table(data_dir / "index_daily.csv")
    if idx is not None:
        idx["date"] = pd.to_datetime(idx["date"])
        idx["code"] = _norm_code(idx["code"])
        index_close = _pivot(idx, "close")
        index_amount = _pivot(idx, "amount") if "amount" in idx else pd.DataFrame(index=index_close.index)
    else:
        index_close = pd.DataFrame(index=sector_close.index)
        index_amount = pd.DataFrame(index=sector_close.index)

    # 交易日历：以行业数据为准
    dates = sector_close.index
    index_close = index_close.reindex(dates)
    index_amount = index_amount.reindex(dates)

    notes = []
    mkt_code = cfg["data"]["market_index"]
    mk = index_close[mkt_code] if mkt_code in index_close else None
    first = mk.first_valid_index() if mk is not None else None
    if first is not None and mk.loc[first:].isna().mean() <= 0.01 and first <= dates[0] + pd.Timedelta(days=400):
        market_close = mk.ffill()
    else:
        from ..core.returns import index_from_returns
        market_close = index_from_returns(sector_close.pct_change(fill_method=None))
        notes.append(f"市场基准 {mkt_code} 缺失或缺失日过多，改用行业等权合成指数作为基准")

    # 成交额分母：默认为全部行业成交额之和（任一行业缺数据的日子记为缺失，避免占比虚高）；
    # total_amount_source="file" 时读 market_amount.csv（全市场成交额，含未分类个股）
    total_amount = sector_amount.sum(axis=1, min_count=sector_amount.shape[1])
    if cfg["data"].get("total_amount_source") == "file" and (data_dir / "market_amount.csv").exists():
        ma = pd.read_csv(data_dir / "market_amount.csv", parse_dates=["date"]).set_index("date")["amount"]
        total_amount = ma.reindex(sector_close.index)
        notes.append("成交占比分母 = 全市场个股成交额（market_amount.csv）")
    total_amount = total_amount.where(total_amount > 0)

    macro = _read_table(data_dir / "macro_daily.csv")
    if macro is not None:
        macro["date"] = pd.to_datetime(macro["date"])
        macro = macro.set_index("date").sort_index()
        macro = macro[~macro.index.duplicated(keep="last")].reindex(dates, method="ffill")

    stocks = _read_table(data_dir / "stock_daily.parquet")
    if stocks is None:
        stocks = _read_table(data_dir / "stock_daily.csv")
    if stocks is not None:
        stocks["date"] = pd.to_datetime(stocks["date"])
        stocks["code"] = _norm_code(stocks["code"])
    ind = _read_table(data_dir / "stock_industry.csv")
    if ind is not None:
        ind["code"] = _norm_code(ind["code"])
        ind["sector"] = _norm_code(ind["sector"])
        ind["start_date"] = pd.to_datetime(ind["start_date"])
    prof = _read_table(data_dir / "stock_profit.csv")
    if prof is not None:
        prof["code"] = _norm_code(prof["code"])
        for c in ("report_date", "ann_date"):
            prof[c] = pd.to_datetime(prof[c])

    groups = {g: [str(c) for c in m] for g, m in cfg.get("groups", {}).items()}
    return MarketData(
        sector_close=sector_close, sector_amount=sector_amount, sector_names=names,
        market_close=market_close, total_amount=total_amount,
        index_close=index_close, index_amount=index_amount, groups=groups,
        macro=macro, stocks=stocks, stock_industry=ind, stock_profit=prof,
        source=f"csv:{data_dir}", notes=notes,
    )


def restrict(data: MarketData, start=None, end=None) -> MarketData:
    """截取日期区间（保留预热期由调用方决定）。"""
    sl = slice(pd.Timestamp(start) if start else None, pd.Timestamp(end) if end else None)
    stocks = data.stocks
    if stocks is not None:
        m = np.ones(len(stocks), dtype=bool)
        if start:
            m &= stocks["date"] >= pd.Timestamp(start)
        if end:
            m &= stocks["date"] <= pd.Timestamp(end)
        stocks = stocks[m]
    return MarketData(
        sector_close=data.sector_close.loc[sl], sector_amount=data.sector_amount.loc[sl],
        sector_names=data.sector_names, market_close=data.market_close.loc[sl],
        total_amount=data.total_amount.loc[sl], index_close=data.index_close.loc[sl],
        index_amount=data.index_amount.loc[sl], groups=data.groups,
        macro=data.macro.loc[sl] if data.macro is not None else None,
        stocks=stocks, stock_industry=data.stock_industry, stock_profit=data.stock_profit,
        source=data.source, notes=list(data.notes),
    )
