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
)
call ".venv\Scripts\activate.bat"

rem Reinstall whenever requirements.txt changes, not only on first run. An
rem existing .venv otherwise keeps running without a dependency added later
rem (yt-dlp-ejs went missing that way and YouTube returned thumbnails only).
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
    echo Updating dependencies...
    pip install -r requirements.txt && copy /y requirements.txt ".venv\requirements.installed" >nul
)

python main.py
if errorlevel 1 pause
