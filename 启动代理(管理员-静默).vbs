' Trae-Poxy 管理员启动脚本（静默模式）
' 此脚本会自动请求管理员权限并在后台启动代理服务

Set objShell = CreateObject("Shell.Application")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' 获取脚本所在目录
strScriptPath = objFSO.GetParentFolderName(WScript.ScriptFullName)

' 构建启动命令
strCommand = "cmd /c cd /d """ & strScriptPath & """ && "

' 检查是否有虚拟环境
If objFSO.FileExists(strScriptPath & "\.venv\Scripts\activate.bat") Then
    strCommand = strCommand & "call .venv\Scripts\activate.bat && "
End If

strCommand = strCommand & "python gui_app.py"

' 以管理员权限运行
objShell.ShellExecute "cmd.exe", "/c " & strCommand, strScriptPath, "runas", 0

' 0 = 隐藏窗口
' 1 = 显示窗口
