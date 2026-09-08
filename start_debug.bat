@echo off
chcp 65001 >nul
cd /d %~dp0

REM 调试启动：用有控制台的 python 前台运行，报错会显示在此窗口，便于排查
REM 运行日志同时写入 data\panel.log。排错结束后按 Ctrl+C 停止，或双击 stop.bat 停止。

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not exist "data" mkdir data
echo [调试模式] 正在前台启动青豆面板（报错会显示在这里，窗口不会自动关闭）...
echo [调试模式] 日志同时写入 data\panel.log
"%PY%" app.py 2>&1 | tee data\panel.log
pause
