"""Zigzag 拐点识别（事后标注波段用）。

注意：zigzag 的峰/谷是“事后”才能确认的——价格从峰回撤满阈值那一天（confirm_idx）
才知道前面是峰。研究里凡是把峰/谷当作结果（顶部、底部、切换点）的地方，
都只用于描述或作为预测目标，绝不能当作 t 日可用的信号。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def zigzag(values: pd.Series, threshold: float, log: bool = True) -> pd.DataFrame:
    """在序列上找交替出现的峰/谷。

    threshold: 反转确认幅度（如 0.2 = 20%）。log=True 时在对数空间比较，
    即峰→谷回撤 ≥ 1-1/(1+th)……为对称起见统一用 log(1+th)。
    返回 DataFrame[pos, date, kind('peak'/'trough'), value, confirmed, confirm_pos]；
    最后一个拐点是“当前极值”，confirmed=False。
    """
    s = values.dropna()
    if len(s) < 3:
        return _empty()
    x = np.log(s.to_numpy(dtype=float)) if log else s.to_numpy(dtype=float)
    th = np.log1p(threshold) if log else threshold
    pos_map = values.index.get_indexer(s.index)

    pivots: list[tuple[int, str, int]] = []  # (i, kind, confirm_i)
    i_max = i_min = 0
    direction = 0  # 1 = 上行中（在找峰），-1 = 下行中（在找谷）
    for i in range(1, len(x)):
        if direction == 0:
            if x[i] > x[i_max]:
                i_max = i
            if x[i] < x[i_min]:
                i_min = i
            if x[i] - x[i_min] >= th and i_min < i:
                pivots.append((i_min, "trough", i))
                direction, i_max = 1, i
            elif x[i_max] - x[i] >= th and i_max < i:
                pivots.append((i_max, "peak", i))
                direction, i_min = -1, i
        elif direction == 1:
            if x[i] > x[i_max]:
                i_max = i
            elif x[i_max] - x[i] >= th:
                pivots.append((i_max, "peak", i))
                direction, i_min = -1, i
        else:
            if x[i] < x[i_min]:
                i_min = i
            elif x[i] - x[i_min] >= th:
                pivots.append((i_min, "trough", i))
                direction, i_max = 1, i

    rows = [
        {"pos": int(pos_map[i]), "date": s.index[i], "kind": k, "value": float(s.iloc[i]),
         "confirmed": True, "confirm_pos": int(pos_map[c])}
        for i, k, c in pivots
    ]
    if direction != 0:
        i_last = i_max if direction == 1 else i_min
        kind = "peak" if direction == 1 else "trough"
        if not rows or rows[-1]["pos"] != pos_map[i_last]:
            rows.append({"pos": int(pos_map[i_last]), "date": s.index[i_last], "kind": kind,
                         "value": float(s.iloc[i_last]), "confirmed": False, "confirm_pos": -1})
    return pd.DataFrame(rows) if rows else _empty()


def filter_short_legs(pivots: pd.DataFrame, values: pd.Series, min_len: int) -> pd.DataFrame:
    """删除短于 min_len 个交易日的波段（合并噪音切换），保持峰谷交替。

    每删除一段后，把每个拐点重新定位到相邻拐点之间的真实极值，避免丢掉真正的峰/谷。
    """
    p = pivots.reset_index(drop=True).copy()
    arr = values.to_numpy(dtype=float)
    while len(p) >= 3:
        lens = p["pos"].diff().iloc[1:]
        short = lens[lens < min_len]
        if short.empty:
            break
        j = int(short.idxmin())  # 短波段 = (j-1, j)
        if j - 1 == 0:
            drop = [0]
        elif j == len(p) - 1:
            drop = [j]
        else:
            drop = [j - 1, j]
        p = p.drop(index=drop).reset_index(drop=True)
        p = _reextremize(p, values, arr)
    return p


def _reextremize(p: pd.DataFrame, values: pd.Series, arr: np.ndarray) -> pd.DataFrame:
    p = p.copy()
    n = len(arr)
    for i in range(len(p)):
        lo = int(p.at[i - 1, "pos"]) + 1 if i > 0 else 0
        hi = int(p.at[i + 1, "pos"]) if i < len(p) - 1 else n
        if hi <= lo:
            continue
        seg = arr[lo:hi]
        if np.all(np.isnan(seg)):
            continue
        k = lo + int(np.nanargmax(seg) if p.at[i, "kind"] == "peak" else np.nanargmin(seg))
        if k != p.at[i, "pos"]:
            p.at[i, "pos"] = k
            p.at[i, "date"] = values.index[k]
            p.at[i, "value"] = float(arr[k])
    return p


def legs(pivots: pd.DataFrame) -> pd.DataFrame:
    """相邻拐点组成的波段表。"""
    if len(pivots) < 2:
        return pd.DataFrame(columns=["start_pos", "end_pos", "start_date", "end_date", "direction", "change", "days", "end_confirmed"])
    a = pivots.iloc[:-1].reset_index(drop=True)
    b = pivots.iloc[1:].reset_index(drop=True)
    return pd.DataFrame({
        "start_pos": a["pos"],
        "end_pos": b["pos"],
        "start_date": a["date"],
        "end_date": b["date"],
        "direction": np.where(a["kind"] == "trough", "up", "down"),
        "change": b["value"].to_numpy() / a["value"].to_numpy() - 1,
        "days": b["pos"].to_numpy() - a["pos"].to_numpy(),
        "end_confirmed": b["confirmed"],
    })


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["pos", "date", "kind", "value", "confirmed", "confirm_pos"])
