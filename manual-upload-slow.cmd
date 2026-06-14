@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
)
if not exist "%LOCALAPPDATA%\EpdStatusDashboard\logs" mkdir "%LOCALAPPDATA%\EpdStatusDashboard\logs"
echo Running one safe EPD image upload with interleaved_count=0 and no pre-upload clear.
echo Console log: "%LOCALAPPDATA%\EpdStatusDashboard\logs\manual-safe-refresh-console.log"
".venv\Scripts\python.exe" windows_epd_upload.py --image-url "http://203.0.113.20:8088/status.png" --scan-timeout 25 --interleaved-count 0 --no-clear-before-upload --clear-cycles 1 --no-clear-refresh --clear-wait-seconds 35 --refresh-wait-seconds 35 --ignore-runtime-config --log-file "%LOCALAPPDATA%\EpdStatusDashboard\logs\manual-safe-refresh.log" > "%LOCALAPPDATA%\EpdStatusDashboard\logs\manual-safe-refresh-console.log" 2>&1
set EXITCODE=%ERRORLEVEL%
type "%LOCALAPPDATA%\EpdStatusDashboard\logs\manual-safe-refresh-console.log"
echo Manual safe refresh exited with %EXITCODE%.
pause
exit /b %EXITCODE%
