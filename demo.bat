@echo off
cd /d "%~dp0"
title Deal bot demo for Pinterest
echo Start your screen recording now, then press any key.
pause >nul
python dealbot.py --demo
echo.
echo Stop the recording. Upload the video when you request Standard access.
pause
