#!/bin/bash
# Claude Code（网页版）会话启动：安装依赖并准备研究数据，使测试与全部研究命令可以直接运行。
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
PY=python3

# 1) Python 依赖（numpy/pandas/scipy + 测试与 parquet 读写）
"$PY" -m pip install --quiet --disable-pip-version-check -e ".[dev]" pyarrow

# 2) 让 ashare_lab / indicator_lab 在任何工作目录下都能导入
echo "export PYTHONPATH=\"$CLAUDE_PROJECT_DIR\${PYTHONPATH:+:\$PYTHONPATH}\"" >> "$CLAUDE_ENV_FILE"

# 3) 研究数据（失败不阻断会话：测试不依赖真实数据，可之后手动运行 scripts/setup_data.sh）
if ! PYTHON="$PY" bash scripts/setup_data.sh; then
  echo "[session-start] 数据准备失败，可稍后手动运行：bash scripts/setup_data.sh" >&2
fi
