@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo   Building WDTT Native Go Executable (Windows)
echo ==============================================
echo.

set "PATH=%PATH%;C:\Program Files\Go\bin;%USERPROFILE%\go\bin"

go build -ldflags="-H windowsgui -s -w" -o WDTT.exe .
if %errorlevel% equ 0 (
    echo.
    echo [✓] Build completed successfully: WDTT.exe is ready!
) else (
    echo.
    echo [!] Build failed!
)

pause
