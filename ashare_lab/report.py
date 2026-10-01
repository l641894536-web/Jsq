"""研究结果容器与 Markdown 报告输出。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PCT_HINTS = ("收益", "超额", "均值", "中位", "胜率", "差值", "CI", "占比", "回撤", "比例", "涨幅", "概率",
             "命中率", "召回", "基准", "波动", "精确率", "跌幅", "阈值", "分位", "涨跌")


@dataclass
class Table:
    title: str
    df: pd.DataFrame
    note: str = ""
    pct_cols: list[str] | None = None   # None = 按列名猜
    max_rows: int = 200


@dataclass
class StudyResult:
    study_id: str
    title: str
    question: str
    definitions: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def add(self, title: str, df: pd.DataFrame, note: str = "", pct_cols: list[str] | None = None, max_rows: int = 200):
        self.tables.append(Table(title, df, note, pct_cols, max_rows))

    def table(self, title: str) -> pd.DataFrame:
        for t in self.tables:
            if t.title == title:
                return t.df
        raise KeyError(title)

    def to_markdown(self) -> str:
        lines = [f"# 研究{self.study_id}｜{self.title}", ""]
        if self.meta.get("synthetic"):
            lines += ["> ⚠️ **合成数据**：本报告只用于检查代码流程，数字不代表任何A股结论。", ""]
        lines += [f"**研究问题**：{self.question}", ""]
        info = [f"- {k}：{v}" for k, v in self.meta.items() if k != "synthetic"]
        if info:
            lines += ["**运行信息**", "", *info, ""]
        if self.findings:
            lines += ["## 结论（自动生成，附证据等级）", ""]
            lines += [f"{i}. {f}" for i, f in enumerate(self.findings, 1)]
            lines += ["", "证据等级：A=样本≥20、FDR校正后q<0.05且前后两段同向；B=样本≥10、q<0.10且同向；"
                          "C=不显著或前后不一致；D=样本<5，不能下结论。", ""]
        if self.definitions:
            lines += ["## 定义（预注册，见 config/default.toml）", ""]
            lines += [f"- {d}" for d in self.definitions]
            lines.append("")
        for t in self.tables:
            lines += [f"## {t.title}", ""]
            if t.note:
                lines += [t.note, ""]
            lines += [df_to_markdown(t.df, t.pct_cols, t.max_rows), ""]
        if self.caveats:
            lines += ["## 局限与注意事项", ""]
            lines += [f"- {c}" for c in self.caveats]
            lines.append("")
        lines.append(f"_生成时间：{datetime.now():%Y-%m-%d %H:%M}_")
        return "\n".join(lines)

    def save(self, out_dir: str | Path) -> Path:
        out = Path(out_dir)
        csv_dir = out / "csv"
        csv_dir.mkdir(parents=True, exist_ok=True)
        for old in csv_dir.glob(f"{self.study_id}_*.csv"):
            old.unlink()   # 清掉本研究上一次的表格（表格编号可能已变）
        path = out / f"{self.study_id}_{self.title}.md"
        path.write_text(self.to_markdown(), encoding="utf-8")
        for i, t in enumerate(self.tables, 1):
            safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in t.title)[:60]
            t.df.to_csv(csv_dir / f"{self.study_id}_{i:02d}_{safe}.csv", index=False, encoding="utf-8-sig")
        return path


NON_PCT = ("天", "(日)", "（日）", "p值", "q值", "t值", "排名", "夏普", "段数", "个数", "样本", "次数",
           "日期", "代码", "证据", "名称", "IC", "β")


def _is_pct_col(col: str) -> bool:
    c = str(col)
    if c == "n" or c.endswith("n") or any(s in c for s in NON_PCT):
        return False
    return any(h in c for h in PCT_HINTS)


def fmt_value(v, pct: bool) -> str:
    if v is None:
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "是" if v else "否"
    if isinstance(v, (pd.Timestamp, datetime)):
        return "" if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d")
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(v):
            return ""
        if pct:
            return f"{v * 100:.1f}%"
        if abs(v) >= 100 or float(v).is_integer():
            return f"{v:.0f}"
        return f"{v:.3f}" if abs(v) < 1 else f"{v:.2f}"
    if v is pd.NaT:
        return ""
    return str(v)


def df_to_markdown(df: pd.DataFrame, pct_cols: list[str] | None = None, max_rows: int = 200) -> str:
    if df is None or df.empty:
        return "_（无数据/无事件）_"
    d = df.head(max_rows)
    cols = list(d.columns)
    pct = set(pct_cols) if pct_cols is not None else {c for c in cols if _is_pct_col(c)}
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(fmt_value(v, c in pct) for c, v in zip(cols, row)) + " |" for row in d.itertuples(index=False)]
    more = [f"\n_（共 {len(df)} 行，仅显示前 {max_rows} 行，完整数据见 csv/ 目录）_"] if len(df) > max_rows else []
    return "\n".join([header, sep, *body, *more])


def pct(v: float, digits: int = 1) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v * 100:.{digits}f}%"


def num(v: float, digits: int = 0) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v:.{digits}f}"
