@echo off
REM Builds RotationTracker.exe from rotation_tracker.py
REM Requires Python 3 (https://www.python.org/downloads/ - tick "Add python.exe to PATH" when installing)

cd /d "%~dp0"
echo Installing PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo.
    echo Python was not found. Install it from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Building exe...
python -m PyInstaller --onefile --windowed --name RotationTracker rotation_tracker.py
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

copy /y "dist\RotationTracker.exe" "RotationTracker.exe" >nul
echo.
echo Done! RotationTracker.exe is in this folder.
pause
