@echo off
cd /d "%~dp0"
title Deal bot test run
set PYTHONIOENCODING=utf-8
echo Test run: finds real deals and shows the pins it WOULD post. Nothing is posted.
echo Please wait about a minute...
python dealbot.py --dry-run --count 10 > testrun.txt 2>&1
type testrun.txt
echo.
echo Saved testrun.txt
pause
