@echo off
chcp 65001 >nul
cd /d %~dp0

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo 正在停止青豆面板...
"%PY%" panel_ctl.py stop

timeout /t 1 >nul
exit
