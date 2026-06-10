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

echo Ensuring WeChat QR OpenCV build...
".venv\Scripts\python.exe" -c "import cv2, sys; sys.exit(0 if hasattr(cv2, 'wechat_qrcode_WeChatQRCode') else 1)" >nul 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.11.0.86
    if errorlevel 1 (
        echo Failed to install OpenCV contrib build.
        pause
        exit /b 1
    )
)

echo Starting bot...
set "OCR_ENGINE=rapidocr"
".venv\Scripts\python.exe" -m bot.main
pause
