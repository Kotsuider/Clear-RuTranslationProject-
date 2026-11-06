@echo off
cd /d "%~dp0"
python translate_tool.py inject-md
echo.
pause
