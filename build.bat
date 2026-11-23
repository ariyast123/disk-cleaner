@echo off
REM Builds dist\DiskCleaner.exe - run this once on the Windows PC.
REM With the argument "auto" (used by finish_update.bat) the build
REM never waits for a keypress - nobody is there to press one.
cd /d %~dp0
python -m pip install --upgrade customtkinter send2trash pyinstaller
if errorlevel 1 goto :error
python -m PyInstaller --onefile --windowed --name DiskCleaner --collect-all customtkinter disk_cleaner_app.py
if errorlevel 1 goto :error
echo.
echo Done: dist\DiskCleaner.exe
if /I not "%~1"=="auto" pause
exit /b 0
:error
echo.
echo Build failed - read the error above.
if /I not "%~1"=="auto" pause
exit /b 1
