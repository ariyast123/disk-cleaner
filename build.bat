@echo off
REM Builds dist\DiskCleaner.exe - run this once on the Windows PC.
cd /d %~dp0
python -m pip install --upgrade customtkinter send2trash pyinstaller
if errorlevel 1 goto :error
python -m PyInstaller --onefile --windowed --name DiskCleaner --collect-all customtkinter disk_cleaner_app.py
if errorlevel 1 goto :error
echo.
echo Done: dist\DiskCleaner.exe
pause
exit /b 0
:error
echo.
echo Build failed - read the error above.
pause
exit /b 1
