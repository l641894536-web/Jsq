#!/bin/bash
# 下载并导入研究用数据（chenditc/investment_data 的 qlib 数据，固定 2026-09-29 版本，sha256 校验）。
# 幂等：已存在的步骤会跳过。用法：bash scripts/setup_data.sh
set -euo pipefail

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
QLIB_ROOT="${QLIB_ROOT:-$(dirname "$REPO_DIR")/qlibdata}"     # 与 config/indicators.toml 的 qlib_dir 一致
QLIB_DIR="$QLIB_ROOT/cn_data"
TAG="2026-09-29"
SHA256="0756a5b7e32842c0f03f09f5483de39074ab3768cda6cc6a10fd0664b6213f65"
URL="https://github.com/chenditc/investment_data/releases/download/${TAG}/qlib_bin.tar.gz"
PY="${PYTHON:-python3}"

mkdir -p "$QLIB_ROOT"
if [ ! -f "$QLIB_DIR/calendars/day.txt" ]; then
  if [ ! -f "$QLIB_ROOT/qlib_bin.tar.gz" ] || ! echo "$SHA256  $QLIB_ROOT/qlib_bin.tar.gz" | sha256sum -c --quiet - 2>/dev/null; then
    echo "[setup_data] 下载 qlib 数据 $TAG（约 570MB）..."
    curl -fL --retry 4 --retry-delay 2 -o "$QLIB_ROOT/qlib_bin.tar.gz.part" "$URL"
    mv "$QLIB_ROOT/qlib_bin.tar.gz.part" "$QLIB_ROOT/qlib_bin.tar.gz"
  fi
  echo "$SHA256  $QLIB_ROOT/qlib_bin.tar.gz" | sha256sum -c --quiet -
  echo "[setup_data] 解压到 $QLIB_DIR ..."
  mkdir -p "$QLIB_DIR"
  tar -zxf "$QLIB_ROOT/qlib_bin.tar.gz" -C "$QLIB_DIR" --strip-components=1
fi

cd "$REPO_DIR"
if [ ! -f data/qlib/stock_daily.parquet ] || [ ! -f data/qlib/stock_industry_static.csv ]; then
  echo "[setup_data] 导入为标准数据目录（行业映射从 PyPI 包数据生成，约几分钟）..."
  "$PY" -m ashare_lab --config config/qlib.toml import-qlib "$QLIB_DIR"
fi
echo "[setup_data] 数据就绪：$QLIB_DIR 与 $REPO_DIR/data/qlib"
