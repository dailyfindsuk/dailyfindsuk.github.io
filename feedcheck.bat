@echo off
cd /d "%~dp0"
echo Checking the Awin feed (takes a minute)...
python feedcheck.py
pause
