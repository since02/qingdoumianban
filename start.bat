@echo off
REM 注意：本文件必须保存为 ANSI/GBK 编码 + CRLF 换行（cmd.exe 的硬要求）。
REM 不要改成 UTF-8，也不要加 chcp 65001：否则含中文的行会被 cmd 按字节偏移切碎，
REM 出现一堆 "'xxx' 不是内部或外部命令"，甚至把裸 python 跑成交互式窗口。
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

REM ========== 首次运行：创建虚拟环境并安装依赖 ==========
if not exist "%PY%" (
  echo [首次运行] 正在创建虚拟环境并安装依赖，请稍候...
  set "GP="
  where python >nul 2>&1 && set "GP=python"
  if not defined GP (
    where py >nul 2>&1 && set "GP=py"
  )
  if not defined GP set "GP=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
  if not exist "!GP!" if /i not "!GP!"=="python" if /i not "!GP!"=="py" (
    echo [错误] 找不到可用的 Python，请先安装 Python 3.9+ 并加入 PATH。
    pause
    exit /b 1
  )
  !GP! -m venv .venv
  if exist "%PY%" (
    "%PY%" -m pip install -r requirements.txt
  )
)

if not exist "%PY%" (
  echo.
  echo [错误] 虚拟环境创建失败（未找到 .venv\Scripts\python.exe）。
  echo        请确认已安装 Python 3.9+，并在命令行里能执行 python -V。
  echo.
  pause
  exit /b 1
)

echo 正在启动青豆面板（后台运行，日志: data\panel.log）...
"%PY%" panel_ctl.py start

echo.
echo 面板已在后台运行，本窗口可以直接关闭。
pause
exit /b 0
