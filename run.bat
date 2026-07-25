@echo off
REM ============================================================
REM  Ultron Translate - Local Launch Script
REM  Uses the correct Python 3.10 interpreter where all packages
REM  (pydirectinput, pywinauto, playwright, etc.) are installed.
REM ============================================================

set PYTHON_EXE=C:\Users\nisha\AppData\Local\Programs\Python\Python310\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python 3.10 not found at: %PYTHON_EXE%
    echo Please update PYTHON_EXE in this script to point to your Python 3.10 installation.
    pause
    exit /b 1
)

echo ============================================================
echo   ULTRON TRANSLATE - Starting Local Server
echo   Python: %PYTHON_EXE%
echo   URL:    http://127.0.0.1:8080
echo ============================================================

cd /d "%~dp0"
"%PYTHON_EXE%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
pause
