@echo off
REM First run sets everything up. After that it just starts the app.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on this machine.
    echo Install it from https://www.python.org/downloads/ and tick
    echo "Add python.exe to PATH" during setup, then run this file again.
    pause
    exit /b 1
)

if not exist .venv (
    echo Setting up for the first time. This takes a minute.
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM Cheap when everything is already installed.
pip install --quiet --disable-pip-version-check -r requirements.txt

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Created a .env file. Open it, paste in a free API key, save it,
    echo then run this file again. Get a key at:
    echo   https://aistudio.google.com/apikey
    echo.
    pause
    exit /b 1
)

streamlit run app.py
