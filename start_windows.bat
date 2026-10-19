@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] 创建 Python 虚拟环境...
  python -m venv .venv
  if errorlevel 1 (
    echo 创建虚拟环境失败，请确认已安装 Python 3.11 及以上版本并加入 PATH。
    pause
    exit /b 1
  )
  echo [2/4] 安装依赖...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败，请检查网络或使用国内镜像源重试。
    pause
    exit /b 1
  )
)

if not exist "data\competition_agent.db" (
  echo [3/4] 初始化数据库并导入演示数据...
  ".venv\Scripts\python.exe" scripts\init_db.py --seed
  ".venv\Scripts\python.exe" scripts\ingest_knowledge.py
)

echo [4/4] 启动服务：http://127.0.0.1:8000
echo 接口文档：http://127.0.0.1:8000/api/docs
echo 按 Ctrl+C 停止。
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
endlocal
