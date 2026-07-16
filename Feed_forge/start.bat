@echo off
title FeedForge Local Server
echo ===================================================
echo               FeedForge Startup Launcher
echo ===================================================
echo.

:: Check virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in .venv/
    echo Please build the environment first before running this script.
    echo.
    pause
    exit /b 1
)

echo [INFO] Starting Flask local server...
echo [INFO] Opening FeedForge UI in browser...
echo.

:: Launch the default browser
start "" "http://127.0.0.1:5000"

:: Start the Flask app
call .venv\Scripts\python.exe app.py

echo.
echo Server stopped.
pause
