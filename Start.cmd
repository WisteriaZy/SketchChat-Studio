@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Missing local Python environment: .venv\Scripts\python.exe
    pause
    exit /b 1
)
echo Anan Chat Box - keep this window open. Press Ctrl+C to stop.
echo Test in your own QQ/WeChat chat: Enter generates and sends an image.
echo Diagnostics are saved to runtime.log in this folder.
".venv\Scripts\python.exe" -B -u "start_debug.py"
set "result=%errorlevel%"
echo.
echo Listener stopped. Exit code: %result%
pause
exit /b %result%
