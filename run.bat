@echo off
title Feed Workspace Launcher
cd /d "%~dp0"

echo Checking dependencies...
python -c "import PySide6" 2>nul
if %ERRORLEVEL% neq 0 (
    echo.
    echo PySide6 is not installed in the active Python environment.
    echo Attempting to install it now via pip...
    echo.
    pip install PySide6
    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] Failed to install PySide6 automatically.
        echo Please ensure pip is installed and running, or run:
        echo   pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

echo Starting Feed Workspace...
start pythonw dashboard.py
exit
