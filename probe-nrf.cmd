@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
)
".venv\Scripts\python.exe" windows_epd_upload.py --probe-gatt --scan-timeout 25
pause
