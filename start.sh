#!/bin/bash
set -e
cd "$(dirname "$0")"
PY=python3
if ! command -v python3 >/dev/null 2>&1; then PY=python; fi
if [ ! -d ".venv" ]; then
  echo "首次运行：创建虚拟环境并安装依赖..."
  "$PY" -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
echo "启动青豆面板..."
.venv/bin/python app.py
