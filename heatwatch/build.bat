@echo off
REM HeatWatch build: installs deps, builds dist\HeatWatch.exe.
REM Called with "auto" by the in-app updater: no pause, output
REM is redirected to update_build.log by the helper.
setlocal
cd /d "%~dp0"

python -m pip install --upgrade customtkinter psutil pystray pillow pyinstaller
if errorlevel 1 goto :fail

set "ICONARG="
if exist heatwatch_icon.ico set "ICONARG=--icon heatwatch_icon.ico"

python -m PyInstaller --onefile --windowed --name HeatWatch %ICONARG% --collect-all customtkinter --noconfirm heatwatch_app.py
if errorlevel 1 goto :fail

echo.
echo Build OK: dist\HeatWatch.exe
if /I not "%~1"=="auto" pause
exit /b 0

:fail
echo.
echo Build FAILED - see the messages above.
if /I not "%~1"=="auto" pause
exit /b 1
