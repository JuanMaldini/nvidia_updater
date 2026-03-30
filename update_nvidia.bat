@echo off
setlocal

:: Re-launch as admin if not already elevated
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath \"%~f0\" -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)
:: Verify it's not the Windows Store stub
python -c "import sys" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python found but not functional ^(Windows Store stub^). Install from https://python.org
    pause
    exit /b 1
)

python update_nvidia.py
pause
