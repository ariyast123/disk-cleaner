@echo off
REM GameMode VPN — build a one-file Windows exe with PyInstaller.
REM Run this in the folder that holds gamemode_vpn_app.py and gamemode_core.py.
setlocal
cd /d "%~dp0"

python -m pip install --upgrade customtkinter psutil pyinstaller
if errorlevel 1 goto :fail

python -m PyInstaller --onefile --windowed --name GameModeVPN --collect-all customtkinter --noconfirm gamemode_vpn_app.py
if errorlevel 1 goto :fail

echo.
echo Done: dist\GameModeVPN.exe
pause
exit /b 0

:fail
echo.
echo BUILD FAILED — read the error above.
pause
exit /b 1
