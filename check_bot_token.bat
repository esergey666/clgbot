@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run run_bot.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m bot.check_token
pause
