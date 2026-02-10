# RFP Radar v8.1 - Task Scheduler Registration
$taskName = "RFP_Radar_v81"
$batPath = Join-Path $PSScriptRoot "run_scheduled.bat"
$workDir = $PSScriptRoot

# Remove existing task if any
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create trigger: weekdays at 09:00
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:00"

# Create action
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $workDir

# Settings
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Register
Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings -RunLevel Highest -Force

# Verify
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    $result = "SUCCESS: $taskName registered (State: $($task.State))"
} else {
    $result = "FAILED: Task not found"
}

$result | Out-File -FilePath (Join-Path $PSScriptRoot "task_result.txt") -Encoding utf8
Write-Host $result
