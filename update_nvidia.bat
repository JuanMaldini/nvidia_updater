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

set "PY_CMD="

:: Prefer python if functional
where python >nul 2>&1
if %errorlevel%==0 (
    python -c "import sys" >nul 2>&1
    if %errorlevel%==0 set "PY_CMD=python"
)

:: Fallback to py launcher
if not defined PY_CMD (
    where py >nul 2>&1
    if %errorlevel%==0 (
        py -3 -c "import sys" >nul 2>&1
        if %errorlevel%==0 set "PY_CMD=py -3"
    )
)

:: Bootstrap Python if missing
if not defined PY_CMD (
    echo [BOOTSTRAP] Python not found. Installing Python 3.12...
    set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    set "PY_EXE=%TEMP%\python-installer.exe"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_EXE%' -UseBasicParsing; exit 0 } catch { exit 1 }"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to download Python installer.
        pause
        exit /b 1
    )

    "%PY_EXE%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1 Include_launcher=1
    if %errorlevel% neq 0 (
        echo [ERROR] Python installation failed.
        pause
        exit /b 1
    )

    where python >nul 2>&1
    if %errorlevel%==0 (
        python -c "import sys" >nul 2>&1
        if %errorlevel%==0 set "PY_CMD=python"
    )
    if not defined PY_CMD (
        where py >nul 2>&1
        if %errorlevel%==0 set "PY_CMD=py -3"
    )
)

if not defined PY_CMD (
    echo [ERROR] Could not initialize Python runtime.
    pause
    exit /b 1
)

%PY_CMD% update_nvidia.py
pause
