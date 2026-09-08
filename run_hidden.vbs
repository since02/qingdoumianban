' 青豆面板 - 通用隐藏窗口启动器
' 用法: wscript //nologo run_hidden.vbs "<命令行>" ["<工作目录>"]
' 以隐藏窗口、不等待的方式运行任意命令，进程独立于调用方控制台。
Option Explicit

Dim shell, cmd, wd
If WScript.Arguments.Count < 1 Then WScript.Quit 1
cmd = WScript.Arguments(0)
wd = ""
If WScript.Arguments.Count >= 2 Then wd = WScript.Arguments(1)

Set shell = CreateObject("WScript.Shell")
If wd <> "" Then shell.CurrentDirectory = wd
shell.Run cmd, 0, False
