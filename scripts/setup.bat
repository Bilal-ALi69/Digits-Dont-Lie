@echo off
REM Digits Dont Lie - Windows entry point.
REM Double-click this file, or run it from cmd.exe:  scripts\setup.bat --update
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
    echo   Install Python 3.11 or newer from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup, then run this again.
    echo.
    pause
    exit /b 1
)

%PYTHON% scripts\setup.py %*
set "CODE=%ERRORLEVEL%"

REM Keep the window open when double-clicked, so the result stays readable.
echo.
pause
exit /b %CODE%
