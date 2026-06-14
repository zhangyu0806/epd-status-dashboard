@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Wait \"$env:LOCALAPPDATA\EpdStatusDashboard\logs\epd-upload.log\""
