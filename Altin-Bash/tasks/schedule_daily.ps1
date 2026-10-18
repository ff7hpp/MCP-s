param(
    [ValidateRange(1,24)][int]$EveryHours = 4,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$taskName = 'Altinbas University Daily Update'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    return
}
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
$runnerPath = Join-Path $PSScriptRoot 'run_daily.py'
if (!(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath $runnerPath)) {
    throw 'DAILY_RUNTIME_MISSING'
}
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.Actions.Execute -ne $pythonPath) {
    throw 'TASK_NAME_CONFLICT: existing task belongs to another checkout'
}
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"{0}"' -f $runnerPath) -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddHours($EveryHours)) -RepetitionInterval (New-TimeSpan -Hours $EveryHours)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
