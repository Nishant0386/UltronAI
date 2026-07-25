# ============================================================
#  Ultron Translate - Local Launch Script (PowerShell)
#  Uses the correct Python 3.10 interpreter where all packages
#  (pydirectinput, pywinauto, playwright, etc.) are installed.
# ============================================================

$PYTHON_EXE = "C:\Users\nisha\AppData\Local\Programs\Python\Python310\python.exe"

if (-not (Test-Path $PYTHON_EXE)) {
    Write-Host "[ERROR] Python 3.10 not found at: $PYTHON_EXE" -ForegroundColor Red
    Write-Host "Please update `$PYTHON_EXE in this script to point to your Python 3.10 installation."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ULTRON TRANSLATE - Starting Local Server" -ForegroundColor Cyan
Write-Host "  Python: $PYTHON_EXE" -ForegroundColor Green
Write-Host "  URL:    http://127.0.0.1:8080" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan

Set-Location $PSScriptRoot
& $PYTHON_EXE -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
