@echo off
cd /d "%~dp0"
title Deal bot demo for Pinterest
echo Before you start:
echo  - Log in to Pinterest in your browser as Daily Finds UK.
echo  - Start your screen recording (whole screen), then press any key.
pause >nul
python dealbot.py --demo
echo.
echo Show the product image and your Pinterest profile for a few seconds, then stop the recording.
pause
