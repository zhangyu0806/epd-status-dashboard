@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
)
".venv\Scripts\python.exe" windows_epd_upload.py --scan-only
echo.
echo If you see a likely nrf/EPD device but epd_service=False, copy its address and run:
echo .venv\Scripts\python.exe windows_epd_upload.py --device-address XX:XX:XX:XX:XX:XX --interleaved-count 0 --no-clear-before-upload --clear-cycles 1 --no-clear-refresh --clear-wait-seconds 35 --refresh-wait-seconds 35 --ignore-runtime-config
pause
