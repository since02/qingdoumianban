@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在停止青豆面板...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 1 >nul
echo 已发送停止信号，面板进程已结束。
timeout /t 2 >nul
exit
