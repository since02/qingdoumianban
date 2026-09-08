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

REM 选择解释器：优先 venv 的 pythonw（无控制台，关闭本窗口不会杀掉面板进程）
if exist ".venv\Scripts\pythonw.exe" (
  set "PY=.venv\Scripts\pythonw.exe"
) else (
  set "PY=pythonw"
)

REM 关键：先停掉旧的面板进程，避免重复点击 start 导致端口被占用、新面板打不开
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 1 >nul

if not exist "data" mkdir data
echo 正在启动青豆面板...
start "" %PY% app.py > data\panel.log 2>&1

REM 等几秒后做健康检查，结果写入日志（端口默认 5700）
powershell -NoProfile -Command "Start-Sleep -Seconds 3; try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:5700/healthz' -TimeoutSec 6 -UseBasicParsing; Add-Content -Path 'data\panel.log' -Value ('[启动检测] HTTP ' + $r.StatusCode + ' 面板已就绪，浏览器访问 http://127.0.0.1:5700') } catch { Add-Content -Path 'data\panel.log' -Value ('[启动检测] 未检测到服务，请查看本文件上方报错；或确认端口后浏览器访问 http://127.0.0.1:5700') }" >nul 2>&1

REM 启动完成，自动关闭本窗口
timeout /t 2 >nul
exit
