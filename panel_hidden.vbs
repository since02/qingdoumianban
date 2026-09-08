' 青豆面板 - Windows 隐藏后台启动器
' 用 WScript.Shell.Run(cmd, 0, False) 启动 python app.py：
'   0     = 完全隐藏窗口（无控制台闪现）
'   False = 不等待，立即返回
' 这样启动的进程独立于调用它的 cmd 窗口，关闭窗口不会把它一起杀掉。
Option Explicit

Dim fso, shell, here, py, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here

' 优先使用虚拟环境里的解释器；不存在则退回系统 python
py = fso.BuildPath(here, ".venv\Scripts\python.exe")
If Not fso.FileExists(py) Then py = "python"

cmd = """" & py & """ """ & fso.BuildPath(here, "app.py") & """"
shell.Run cmd, 0, False
