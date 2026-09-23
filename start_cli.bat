@echo off
setlocal enabledelayedexpansion
net session >nul 2>&1
if errorlevel 1 (
    echo [!] Error: Please run start_cli.bat as Administrator!
    pause
    exit /b 1
)

cd /d "%~dp0"

for /f "usebackq tokens=1,* delims==" %%a in ("config.ini") do (
    set "key=%%a"
    set "val=%%b"
    if defined key (
        set "firstchar=!key:~0,1!"
        if not "!firstchar!"=="#" (
            set "!key!=!val!"
        )
    )
)

echo [*] Starting VK TURN Client (Standard DTLS Mode)...
echo [*] Peer: %PEER%
echo [*] Workers: %WORKERS%
echo.

vk-turn-client.exe -mode vpn -peer "%PEER%" -password "%PASSWORD%" -vk "%VK_HASH%" -n %WORKERS%

pause
