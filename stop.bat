@echo off
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo 正在停止青豆面板...
"%PY%" panel_ctl.py stop

echo.
pause
exit /b 0
