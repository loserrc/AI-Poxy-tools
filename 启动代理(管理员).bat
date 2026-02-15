@echo off
:: Trae-Poxy 管理员启动脚本
:: 此脚本会自动请求管理员权限并启动代理服务

:: 检查是否已经是管理员权限
net session >nul 2>&1
if %errorLevel% == 0 (
    echo 已获得管理员权限，正在启动代理...
    goto :run
) else (
    echo 请求管理员权限...
    goto :elevate
)

:elevate
:: 请求管理员权限并重新运行此脚本
powershell -Command "Start-Process '%~f0' -Verb RunAs"
exit /b

:run
:: 切换到脚本所在目录
cd /d "%~dp0"

:: 启动代理服务
echo.
echo ========================================
echo Trae-Poxy 代理服务
echo ========================================
echo.
echo 正在启动代理服务...
echo.

:: 如果有虚拟环境，先激活
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

:: 启动 GUI 应用
python gui_app.py

:: 如果 GUI 关闭，保持窗口打开
echo.
echo 代理服务已停止。
pause
