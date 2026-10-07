@echo off
:: Self-elevation check
openfiles >nul 2>&1
if '%errorlevel%' NEQ '0' (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo Processing...

taskkill /f /im ExHIBIT.exe >nul 2>&1
attrib -r -s -h "userdata\config.rnf" >nul 2>&1
takeown /f "userdata\config.rnf" /a >nul 2>&1
icacls "userdata\config.rnf" /reset >nul 2>&1
icacls "userdata\config.rnf" /grant:r "*S-1-1-0":(F) >nul 2>&1
icacls "userdata" /grant:r "*S-1-1-0":(OI)(CI)(F) /t >nul 2>&1

echo Done!
pause
