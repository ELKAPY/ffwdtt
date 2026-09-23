@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo   Building WDTT Standalone Windows Executable
echo ==============================================
echo.

:: Ensure dependencies are installed
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [!] Failed to install dependencies.
    pause
    exit /b %errorlevel%
)

:: Compile with PyInstaller
pyinstaller --noconsole --onefile --uac-admin --icon="app_icon.ico" --name="WDTT" --collect-all customtkinter --collect-all darkdetect --collect-all pystray --add-data "app_icon.png;." --add-data "app_icon.ico;." main.py

if %errorlevel% equ 0 (
    echo.
    echo [*] Copying WDTT.exe to root folder...
    copy /Y "dist\WDTT.exe" "%~dp0WDTT.exe"
    echo.
    echo [✓] Build completed successfully: WDTT.exe is ready!
) else (
    echo.
    echo [!] Build failed!
)

pause
