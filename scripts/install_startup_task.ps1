# Registers the engine to start at boot, without anyone logging in. Needs admin (UAC).
$repo = "C:\Users\Administrator\Documents\gits\trading-research-engine"
$log = "T:\making-money\engine\install_task.log"
try {
  $action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" -Argument "-m scripts.engine_supervisor" -WorkingDirectory $repo
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $trigger.Delay = "PT1M"
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName "TradingEngine" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  "$(Get-Date -Format s) OK: $((Get-ScheduledTask -TaskName TradingEngine).State)" | Out-File -Append $log
} catch {
  "$(Get-Date -Format s) FAILED: $($_.Exception.Message)" | Out-File -Append $log
}
