param(
    [string]$TaskName = "EpdStatusDashboardUpload",
    [string]$InstallDir = "$env:LOCALAPPDATA\EpdStatusDashboard",
    [switch]$RemoveFiles
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task: $TaskName"
} else {
    Write-Host "Scheduled task not found: $TaskName"
}

if ($RemoveFiles) {
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    Write-Host "Removed install dir: $InstallDir"
}
