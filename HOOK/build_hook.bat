@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PATH=C:\msys64\mingw32\bin;%PATH%
set TMP=%USERPROFILE%\AppData\Local\Temp
set TEMP=%USERPROFILE%\AppData\Local\Temp

echo Building version.dll...
gcc.exe -O2 -shared -s -o ..\..\version.dll proxy_version.c version.def -lversion -lgdi32 -luser32 -Wl,--enable-stdcall-fixup
if %ERRORLEVEL% equ 0 (
    echo [OK] version.dll successfully compiled to game folder!
) else (
    echo [ERROR] Compilation failed.
)
