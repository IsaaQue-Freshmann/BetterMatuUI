@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   BetterMatuUI Beta 1.2  Windows 打包
echo ============================================
echo.

echo [1/4] 创建虚拟环境
if not exist .venv (
    py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
    echo   创建失败：请先安装 Python 3.9 或更高版本，并勾选 "Add to PATH"
    pause & exit /b 1
)

echo [2/4] 安装依赖（首次约几分钟）
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\pip install -q -r requirements.txt pyinstaller
if errorlevel 1 ( echo   依赖安装失败 & pause & exit /b 1 )

echo [3/4] 打包成单文件 exe
.venv\Scripts\pyinstaller --noconfirm --distpath build --workpath work packaging\BetterMatuUI.spec
if errorlevel 1 ( echo   打包失败 & pause & exit /b 1 )

echo [4/4] 完成
echo.
echo   产物： %cd%\build\BetterMatuUI.exe
dir /b build
echo.
pause
