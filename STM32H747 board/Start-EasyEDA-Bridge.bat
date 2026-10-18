@echo off
setlocal EnableExtensions
title STM32H747 EasyEDA API Bridge
rem Optional machine-specific settings; excluded from Git.
if exist "%~dp0EasyEDA-Bridge.local.cmd" call "%~dp0EasyEDA-Bridge.local.cmd"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-EasyEDA-Bridge.ps1" %*
set "BRIDGE_EXIT=%ERRORLEVEL%"
if /i "%~1"=="-Check" exit /b %BRIDGE_EXIT%
echo.
pause
exit /b %BRIDGE_EXIT%

