#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/4] 创建 Python 虚拟环境..."
  python3 -m venv .venv
  echo "[2/4] 安装依赖..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

if [ ! -f "data/competition_agent.db" ]; then
  echo "[3/4] 初始化数据库并导入演示数据..."
  .venv/bin/python scripts/init_db.py --seed
  .venv/bin/python scripts/ingest_knowledge.py
fi

echo "[4/4] 启动服务：http://127.0.0.1:8000"
echo "接口文档：http://127.0.0.1:8000/api/docs"
exec .venv/bin/python -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
