@echo off
chcp 65001 >nul
cd /d %~dp0

REM 全局 Python（仅用于首次创建虚拟环境）
set "GP=python"
where python >nul 2>&1 || set "GP=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"

REM 首次运行：创建虚拟环境并安装依赖
if not exist ".venv\Scripts\python.exe" (
  echo 首次运行：创建虚拟环境并安装依赖...
  "%GP%" -m venv .venv
  if exist ".venv\Scripts\pip.exe" call .venv\Scripts\pip install -r requirements.txt
)

REM 选择解释器：优先 venv 的 python（用普通 python.exe；不用 pythonw，避免无控制台时 print 导致进程静默退出）
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo 正在启动青豆面板（后台运行，日志: data\panel.log）...
"%PY%" panel_ctl.py start

REM 短暂显示结果后自动关闭本窗口
timeout /t 2 >nul
exit
