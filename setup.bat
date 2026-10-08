@echo off
cd /d "%~dp0"
title Deal bot setup
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed.
  echo Install it from https://www.python.org/downloads/
  echo and TICK "Add python.exe to PATH" on the first screen, then run this again.
  pause
  exit /b
)
echo Installing the libraries the bot needs...
python -m pip install --quiet -r requirements.txt
python setup.py
echo.
pause
