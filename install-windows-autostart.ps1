param(
    [string]$InstallDir = "$env:LOCALAPPDATA\EpdStatusDashboard",
    [string]$ImageUrl = "http://203.0.113.20:8088/status.png",
    [string]$DeviceNameHint = "",
    [string]$DeviceAddress = "",
    [double]$ScanTimeout = 25,
    [int]$IntervalSeconds = 600,
    [int]$InterleavedCount = 0,
    [bool]$ClearBeforeUpload = $false,
    [int]$ClearCycles = 1,
    [bool]$ClearRefresh = $false,
    [int]$SafeRefreshClearCycles = 1,
    [double]$ClearWaitSeconds = 35,
    [double]$RefreshWaitSeconds = 35,
    [string]$TaskName = "EpdStatusDashboardUpload"
)

$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallPath = [System.IO.Path]::GetFullPath($InstallDir)
$LogDir = Join-Path $InstallPath "logs"
$LogFile = Join-Path $LogDir "epd-upload.log"
$RuntimeConfigFile = Join-Path $InstallPath "epd-upload-runtime.json"
$LauncherFile = Join-Path $InstallPath "run-upload-daemon.cmd"
$SafeRefreshFile = Join-Path $InstallPath "run-safe-refresh.cmd"
$SafeRefreshLogFile = Join-Path $LogDir "safe-refresh.log"
$SafeRefreshConsoleLogFile = Join-Path $LogDir "safe-refresh-console.log"

New-Item -ItemType Directory -Force -Path $InstallPath | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Copy-Item -Force (Join-Path $SourceDir "windows_epd_upload.py") $InstallPath
Copy-Item -Force (Join-Path $SourceDir "requirements-windows.txt") $InstallPath

Push-Location $InstallPath
try {
    py -m venv .venv
    & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
} finally {
    Pop-Location
}

$PythonExe = Join-Path $InstallPath ".venv\Scripts\pythonw.exe"
$ScriptPath = Join-Path $InstallPath "windows_epd_upload.py"
$ClearBeforeUploadArg = if ($ClearBeforeUpload) { "--clear-before-upload" } else { "--no-clear-before-upload" }
$ClearRefreshArg = if ($ClearRefresh) { "--clear-refresh" } else { "--no-clear-refresh" }
$ArgsList = @(
    "`"$ScriptPath`"",
    "--daemon",
    "--image-url", "`"$ImageUrl`"",
    "--interval-seconds", "$IntervalSeconds",
    "--interleaved-count", "$InterleavedCount",
    $ClearBeforeUploadArg,
    "--clear-cycles", "$ClearCycles",
    $ClearRefreshArg,
    "--clear-wait-seconds", "$ClearWaitSeconds",
    "--refresh-wait-seconds", "$RefreshWaitSeconds",
    "--log-file", "`"$LogFile`""
)

if ($DeviceNameHint.Trim().Length -gt 0) {
    $ArgsList += @("--device-name-hint", "`"$DeviceNameHint`"")
}

if ($DeviceAddress.Trim().Length -gt 0) {
    $ArgsList += @("--device-address", "`"$DeviceAddress`"")
}

$RuntimeDeviceNameHint = $null
if ($DeviceNameHint.Trim().Length -gt 0) {
    $RuntimeDeviceNameHint = $DeviceNameHint
}

$RuntimeDeviceAddress = $null
if ($DeviceAddress.Trim().Length -gt 0) {
    $RuntimeDeviceAddress = $DeviceAddress
}

$RuntimeConfig = [ordered]@{
    image_url = $ImageUrl
    interval_seconds = $IntervalSeconds
    scan_timeout = $ScanTimeout
    interleaved_count = $InterleavedCount
    clear_before_upload = $ClearBeforeUpload
    clear_cycles = $ClearCycles
    clear_refresh = $ClearRefresh
    clear_wait_seconds = $ClearWaitSeconds
    refresh_wait_seconds = $RefreshWaitSeconds
    device_name_hint = $RuntimeDeviceNameHint
    device_address = $RuntimeDeviceAddress
}
$RuntimeConfigJson = $RuntimeConfig | ConvertTo-Json -Depth 3
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($RuntimeConfigFile, $RuntimeConfigJson, $Utf8NoBom)

$LauncherContent = @(
    "@echo off",
    "setlocal",
    "cd /d `"%~dp0`"",
    "`"$PythonExe`" $($ArgsList -join " ")"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText($LauncherFile, $LauncherContent + [Environment]::NewLine, $Utf8NoBom)

$SafePythonExe = Join-Path $InstallPath ".venv\Scripts\python.exe"
$SafeArgsList = @(
    "`"$ScriptPath`"",
    "--image-url", "`"$ImageUrl`"",
    "--scan-timeout", "$ScanTimeout",
    "--interleaved-count", "0",
    "--no-clear-before-upload",
    "--clear-cycles", "$SafeRefreshClearCycles",
    "--no-clear-refresh",
    "--clear-wait-seconds", "$ClearWaitSeconds",
    "--refresh-wait-seconds", "$RefreshWaitSeconds",
    "--ignore-runtime-config",
    "--log-file", "`"$SafeRefreshLogFile`""
)

if ($DeviceNameHint.Trim().Length -gt 0) {
    $SafeArgsList += @("--device-name-hint", "`"$DeviceNameHint`"")
}

if ($DeviceAddress.Trim().Length -gt 0) {
    $SafeArgsList += @("--device-address", "`"$DeviceAddress`"")
}

$SafeRefreshContent = @(
    "@echo off",
    "setlocal",
    "cd /d `"%~dp0`"",
    "echo Running one safe EPD image upload with interleaved_count=0 and no pre-upload clear.",
    "echo Console log: `"$SafeRefreshConsoleLogFile`"",
    "`"$SafePythonExe`" $($SafeArgsList -join " ") > `"$SafeRefreshConsoleLogFile`" 2>&1",
    "set EXITCODE=%ERRORLEVEL%",
    "type `"$SafeRefreshConsoleLogFile`"",
    "echo Safe refresh exited with %EXITCODE%.",
    "exit /b %EXITCODE%"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText($SafeRefreshFile, $SafeRefreshContent + [Environment]::NewLine, $Utf8NoBom)

$Action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/c `"$LauncherFile`"" -WorkingDirectory $InstallPath
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Upload OC24 status dashboard to EPD-nRF5 over BLE" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed EPD Status Dashboard uploader."
Write-Host "Install dir: $InstallPath"
Write-Host "Task name: $TaskName"
Write-Host "Log file: $LogFile"
Write-Host "Runtime config: $RuntimeConfigFile"
Write-Host "Launcher: $LauncherFile"
Write-Host "Safe refresh: $SafeRefreshFile"
Write-Host "To inspect: Get-ScheduledTask -TaskName $TaskName"
Write-Host "To tail log: Get-Content -Wait `"$LogFile`""
