@echo off
chcp 65001 >nul
cd /d %~dp0
set "PY=python"
where python >nul 2>&1 || set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist ".venv" (
  echo 正在创建虚拟环境并安装依赖(首次运行)...
  "%PY%" -m venv .venv
  call .venv\Scripts\pip install -r requirements.txt
)
echo 启动青豆面板...
.venv\Scripts\python app.py
pause
