@echo off
REM ============================================================
REM  Ultron Translate - Standalone Native Desktop Agent App
REM ============================================================

set PYTHON_EXE=C:\Users\nisha\AppData\Local\Programs\Python\Python310\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python 3.10 not found at: %PYTHON_EXE%
    echo Please update PYTHON_EXE in this script to point to your Python 3.10 installation.
    pause
    exit /b 1
)

echo ============================================================
echo   ULTRON TRANSLATE - Starting Desktop Assistant Application
echo   Python: %PYTHON_EXE%
echo   Mode:   Native Desktop Agent (PyWebView + Edge Chromium)
echo ============================================================

cd /d "%~dp0"
"%PYTHON_EXE%" desktop_app.py
pause
