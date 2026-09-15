@echo off
setlocal
cd /d "%~dp0"

REM 调试启动：前台运行，报错直接显示在本窗口（同时由 app.py 写入 data\panel.log）
REM 退出方式：本窗口按 Ctrl+C，或关闭本窗口后双击 stop.bat

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "data" mkdir data

echo [调试模式] 前台启动青豆面板，报错会显示在这里（窗口不会自动关闭）...
echo [调试模式] 日志同时写入 data\panel.log
echo.

"%PY%" app.py

echo.
echo [已退出] 如果上面有报错，请截图反馈。
pause
