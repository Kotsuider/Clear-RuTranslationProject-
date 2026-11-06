@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo ========================================================
    echo   OpenEXhibit GYU ^<--^> PNG Converter ^(UI / CG / BG^)
    echo ========================================================
    echo.
    echo Usage:
    echo   Drag and drop any .gyu or .png file^(s^) onto this file!
    echo.
    echo Commands:
    echo   gyu_converter.bat unpack ^<gyu_folder^> ^<out_png_folder^>
    echo   gyu_converter.bat pack   ^<png_folder^> ^<out_gyu_folder^>
    echo   gyu_converter.bat ^<input.gyu^> [output.png]
    echo   gyu_converter.bat ^<input.png^> [output.gyu]
    echo.
    exit /b 0
)

python "%~dp0gyu_converter.py" %*
