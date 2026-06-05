@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Creating .venv...
    py -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Install Python and try again.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo Starting bot...
".venv\Scripts\python.exe" -m bot.main
pause
