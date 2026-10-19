@echo off
REM Digits Dont Lie - Windows entry point for starting both servers.
REM Double-click this file, or run it from cmd.exe:  scripts\run.bat --dev
setlocal
cd /d "%~dp0.."

set "PYTHON="
where py >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
    where python >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
    echo.
    echo   Python was not found on this machine.
    echo   Run scripts\setup.bat first.
    echo.
    pause
    exit /b 1
)

%PYTHON% scripts\run.py %*
set "CODE=%ERRORLEVEL%"

echo.
pause
exit /b %CODE%
