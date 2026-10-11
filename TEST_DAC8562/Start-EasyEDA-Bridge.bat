@echo off
setlocal EnableExtensions
title EasyEDA API Bridge

set "BRIDGE_SCRIPT=%USERPROFILE%\.codex\skills\easyeda-api\scripts\bridge-server.mjs"
set "NODE_EXE="

if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\node.exe" set "NODE_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Links\node.exe"

if not defined NODE_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_*") do (
        for /d %%V in ("%%~fD\node-v*-win-x64") do (
            if exist "%%~fV\node.exe" set "NODE_EXE=%%~fV\node.exe"
        )
    )
)

if not defined NODE_EXE (
    for /f "delims=" %%N in ('where.exe node.exe 2^>nul') do if not defined NODE_EXE set "NODE_EXE=%%~fN"
)

if not defined NODE_EXE (
    echo [ERROR] Node.js was not found.
    echo Restart Windows or reinstall Node.js, then try again.
    echo.
    pause
    exit /b 1
)

if not exist "%BRIDGE_SCRIPT%" (
    echo [ERROR] EasyEDA API Bridge was not found.
    echo Expected: "%BRIDGE_SCRIPT%"
    echo.
    pause
    exit /b 1
)

echo Starting EasyEDA API Bridge...
echo Node: "%NODE_EXE%"
echo Press Ctrl+C or close this window to stop the server.
echo.

"%NODE_EXE%" "%BRIDGE_SCRIPT%"
set "BRIDGE_EXIT=%ERRORLEVEL%"

echo.
if not "%BRIDGE_EXIT%"=="0" (
    echo [ERROR] Bridge stopped with exit code %BRIDGE_EXIT%.
) else (
    echo Bridge stopped.
)
pause
exit /b %BRIDGE_EXIT%
