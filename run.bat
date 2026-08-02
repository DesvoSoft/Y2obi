@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from https://python.org and re-run this file.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Setting up Y2obi for the first time, this only happens once...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

python main.py
if errorlevel 1 pause
