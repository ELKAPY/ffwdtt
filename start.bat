@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0WDTT.exe" (
    start "" "%~dp0WDTT.exe"
    exit /b
)

:: Fallback to python if exe is not found
start "" pythonw main.py
if errorlevel 1 (
    python main.py
)
exit /b
