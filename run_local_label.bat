@echo off
setlocal
cd /d "%~dp0"

set "BOOTSTRAP_PY=C:\Users\spime\AppData\Local\Programs\Python\Python313\python.exe"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo Existing virtual environment is broken or was moved. Recreating .venv...
        ren ".venv" ".venv_broken_%RANDOM%"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Creating .venv...
    if exist "%BOOTSTRAP_PY%" (
        "%BOOTSTRAP_PY%" -m venv .venv
    ) else (
        py -m venv .venv
    )
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

echo Generating local test label...
".venv\Scripts\python.exe" -m bot.local_label --art 761530404 --color V0158 --size 30 --code TOM068804 --certilogo-code CLG047604293519 --certilogo-url https://certilogo.com/CLG047604293519 --output data\local_label.png
pause
