"""Shared helpers: schemas, partitioned CSV storage, stage status."""
from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

EXT = ".csv.xz"
XZ = {"method": "xz", "preset": 6}


# ---------------------------------------------------------------- schema io
# A schema is {column: kind}; kind is "str", "int", or ("float", decimals).

def normalize(df: pd.DataFrame, schema: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col, kind in schema.items():
        s = df[col] if col in df.columns else pd.Series([None] * len(df), index=df.index)
        if kind == "str":
            s = s.astype(object).where(s.notna(), "")
            out[col] = s.astype(str).replace({"nan": "", "None": ""})
        elif kind == "int":
            out[col] = pd.to_numeric(s, errors="coerce").round(0).astype("Int64")
        else:
            out[col] = pd.to_numeric(s, errors="coerce").round(kind[1]).astype("float64")
    return out


def read_csv(path: Path, schema: dict | None = None) -> pd.DataFrame:
    if schema is None:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    dtypes = {}
    for col, kind in schema.items():
        dtypes[col] = str if kind == "str" else ("Int64" if kind == "int" else "float64")
    df = pd.read_csv(path, dtype=dtypes, keep_default_na=False, na_values=[""])
    for col, kind in schema.items():
        if kind == "str" and col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    return df


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    comp = XZ if path.name.endswith(".xz") else None
    df.to_csv(tmp, index=False, compression=comp)
    os.replace(tmp, path)


def part_path(base: Path, month: str) -> Path:
    return base / month[:4] / f"{month}{EXT}"


def merge_partitioned(new: pd.DataFrame, base: Path, keys: list[str], time_col: str,
                      schema: dict) -> int:
    """Upsert rows into monthly partitions base/YYYY/YYYY-MM.csv.xz. New rows win on key clash.
    Returns the net number of rows added."""
    if new is None or new.empty:
        return 0
    new = normalize(new, schema)
    months = new[time_col].str.slice(0, 7)
    added = 0
    sort_cols = [time_col] + [k for k in keys if k != time_col]
    for month, part in new.groupby(months, sort=True):
        if len(month) != 7:
            continue
        p = part_path(base, month)
        n_old = 0
        if p.exists():
            old = read_csv(p, schema)
            n_old = len(old)
            comb = pd.concat([old, part], ignore_index=True)
        else:
            comb = part
        comb = comb.drop_duplicates(keys, keep="last").sort_values(sort_cols).reset_index(drop=True)
        added += len(comb) - n_old
        write_csv(comb, p)
    return added


def replace_rows(new: pd.DataFrame, path: Path, key: str, schema: dict) -> pd.DataFrame:
    """Single-file table: drop every existing row whose `key` appears in `new`, then append `new`."""
    new = normalize(new, schema)
    if path.exists():
        old = read_csv(path, schema)
        old = old[~old[key].isin(set(new[key]))]
        new = pd.concat([old, new], ignore_index=True)
    write_csv(new, path)
    return new


def load_state(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists():
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for c in columns:
            if c not in df.columns:
                df[c] = ""
        return df[columns]
    return pd.DataFrame(columns=columns, dtype=str)


def save_state(df: pd.DataFrame, path: Path) -> None:
    write_csv(df.fillna(""), path)


# ---------------------------------------------------------------- status

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Stage:
    def __init__(self, name: str):
        self.name = name
        self.t0 = time.time()
        self.info: dict = {"ok": False}
        self.errors: list[str] = []
        self.n_errors = 0

    def error(self, msg: str) -> None:
        self.n_errors += 1
        if len(self.errors) < 40:
            self.errors.append(msg[:400])
        print(f"[{self.name}] ERROR {msg[:400]}", flush=True)

    def log(self, msg: str) -> None:
        print(f"[{self.name}] {time.strftime('%H:%M:%S')} {msg}", flush=True)

    def crash(self, exc: BaseException) -> None:
        self.error("STAGE CRASH: " + "".join(traceback.format_exception(exc))[-1500:])

    def result(self) -> dict:
        d = dict(self.info)
        d["seconds"] = round(time.time() - self.t0, 1)
        d["n_errors"] = self.n_errors
        d["errors"] = self.errors
        return d


def write_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
