@echo off
echo ========================================
echo HannaMed RPA Installer Builder
echo ========================================
echo.

REM Verify we are in the correct directory
if not exist "gui.py" (
    echo ERROR: gui.py not found
    echo Please run this script from the hanna-med-ma-rpa folder
    pause
    exit /b 1
)

REM Verify cloudflared.exe exists
if not exist "bin\cloudflared.exe" (
    echo ERROR: bin\cloudflared.exe not found
    echo Please download cloudflared and copy it to bin\cloudflared.exe
    pause
    exit /b 1
)

echo [1/4] Checking virtual environment...
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

echo [2/4] Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo.
echo [3/4] Compiling executable with PyInstaller...
echo This may take several minutes...
pyinstaller hannamed-rpa.spec

if not exist "dist\HannaMedRPA.exe" (
    echo ERROR: Failed to create executable
    echo Check PyInstaller errors above
    pause
    exit /b 1
)

echo.
echo ✓ Executable created: dist\HannaMedRPA.exe
echo Size: 
dir dist\HannaMedRPA.exe | find "HannaMedRPA.exe"

echo.
echo [4/4] Compiling installer with NSIS...

REM Find makensis.exe in common paths
set NSIS_PATH=
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set NSIS_PATH=C:\Program Files (x86)\NSIS\makensis.exe
if exist "C:\Program Files\NSIS\makensis.exe" set NSIS_PATH=C:\Program Files\NSIS\makensis.exe

if "%NSIS_PATH%"=="" (
    echo ERROR: NSIS not found
    echo Please install NSIS from https://nsis.sourceforge.io/Download
    echo Or manually specify the path to makensis.exe
    pause
    exit /b 1
)

echo Using NSIS: %NSIS_PATH%
"%NSIS_PATH%" installer\installer.nsi

if not exist "installer\HannaMed-RPA-Setup.exe" (
    echo ERROR: Failed to create installer
    echo Check NSIS errors above
    pause
    exit /b 1
)

echo.
echo ========================================
echo ✓ BUILD COMPLETED SUCCESSFULLY
echo ========================================
echo.
echo Installer created: installer\HannaMed-RPA-Setup.exe
echo.
dir installer\HannaMed-RPA-Setup.exe | find "HannaMed-RPA-Setup.exe"
echo.
echo ========================================
echo.
pause
