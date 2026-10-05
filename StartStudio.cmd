@echo off
setlocal
if not exist "%~dp0StartStudio.exe" (
    echo Missing StartStudio.exe. Rebuild using launcher\Build.ps1.
    pause
    exit /b 1
)
start "" "%~dp0StartStudio.exe"
exit /b
