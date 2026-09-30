"""各研究共用的基础面板（只算一次）。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

from ..core import returns as R
from ..core.stats import GradeRule, grade_rule_from_cfg
from ..data.market import MarketData


@dataclass
class Panels:
    data: MarketData
    cfg: dict

    # ---- 基础 ----
    @cached_property
    def ret(self) -> pd.DataFrame:
        return R.daily_return(self.data.sector_close)

    @cached_property
    def mret(self) -> pd.Series:
        return R.daily_return(self.data.market_close)

    @cached_property
    def rs(self) -> pd.DataFrame:
        """相对强弱线 = 行业 / 市场（起点归一）。"""
        rs = self.data.sector_close.div(self.data.market_close, axis=0)
        return rs / rs.bfill().iloc[0]

    def exc_past(self, n: int) -> pd.DataFrame:
        return R.excess(R.past_return(self.data.sector_close, n), R.past_return(self.data.market_close, n))

    @cached_property
    def exc20(self) -> pd.DataFrame:
        return self.exc_past(20)

    @cached_property
    def exc60(self) -> pd.DataFrame:
        return self.exc_past(60)

    @cached_property
    def rank60(self) -> pd.DataFrame:
        return R.rank_desc(self.exc60)

    @cached_property
    def share(self) -> pd.DataFrame:
        return self.data.turnover_share()

    @cached_property
    def share_pct(self) -> pd.DataFrame:
        c = self.cfg["common"]
        return R.rolling_percentile_frame(self.share, c["pct_window"], c["pct_min_periods"])

    # ---- 前瞻（只用于评估）----
    def fwd_ret(self, h: int, lag: int | None = None) -> pd.DataFrame:
        return R.fwd_return(self.data.sector_close, h, self.lag if lag is None else lag)

    def fwd_exc(self, h: int, lag: int | None = None) -> pd.DataFrame:
        lag = self.lag if lag is None else lag
        return R.excess(R.fwd_return(self.data.sector_close, h, lag), R.fwd_return(self.data.market_close, h, lag))

    def fwd_mdd(self, h: int, lag: int | None = None) -> pd.DataFrame:
        return R.fwd_min_return(self.data.sector_close, h, self.lag if lag is None else lag)

    # ---- 配置 ----
    @property
    def lag(self) -> int:
        return int(self.cfg["common"]["entry_lag"])

    @property
    def horizons(self) -> list[int]:
        return list(self.cfg["common"]["horizons"])

    @property
    def split(self) -> pd.Timestamp:
        return pd.Timestamp(self.cfg["common"]["split_date"])

    @property
    def study_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.cfg["data"]["study_start"])

    @property
    def study_end(self) -> pd.Timestamp:
        return pd.Timestamp(self.cfg["data"]["study_end"])

    @property
    def period(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.study_start, self.study_end

    @cached_property
    def rng(self) -> np.random.Generator:
        return np.random.default_rng(int(self.cfg["common"]["seed"]))

    @property
    def grade_rule(self) -> GradeRule:
        return grade_rule_from_cfg(self.cfg)

    def in_study(self, dates) -> np.ndarray:
        d = pd.DatetimeIndex(dates)
        return np.asarray((d >= self.study_start) & (d <= self.study_end))

    def meta(self) -> dict:
        d = self.data.dates
        m = {
            "数据": self.data.summary(),
            "研究区间": f"{max(d.min(), self.study_start).date()} ~ {min(d.max(), self.study_end).date()}",
            "入场": f"信号日后第 {self.lag} 个交易日收盘入场" if self.lag else "信号日收盘入场",
            "前后分段": f"≤{self.split.date()} / >{self.split.date()}",
            "synthetic": self.data.is_synthetic,
        }
        if self.data.notes:
            m["数据备注"] = "；".join(self.data.notes)
        return m


def pos_of(index: pd.DatetimeIndex, date) -> int:
    return int(index.get_loc(pd.Timestamp(date)))


def first_true(mask: np.ndarray, lo: int, hi: int) -> int | None:
    """[lo, hi] 区间内第一个 True 的位置。"""
    if hi < lo:
        return None
    seg = np.flatnonzero(mask[lo:hi + 1])
    return int(lo + seg[0]) if len(seg) else None
