"""读取预注册参数（config/default.toml）。"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.toml"


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict:
    """读取 TOML 配置；overrides 形如 {"common.entry_lag": 0}，用于稳健性检验。"""
    with open(path or DEFAULT_CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    for dotted, value in (overrides or {}).items():
        set_dotted(cfg, dotted, value)
    return cfg


def set_dotted(cfg: dict, dotted: str, value: Any) -> None:
    node = cfg
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node.setdefault(key, {})
    node[leaf] = value


def with_overrides(cfg: dict, overrides: dict[str, Any]) -> dict:
    out = copy.deepcopy(cfg)
    for dotted, value in overrides.items():
        set_dotted(out, dotted, value)
    return out
