# ============================================================================
#  Windows Task Scheduler setup - run once (as Administrator) to register:
#    GasShortTerm_DataUpdate  daily 07:45  -> update_data.ps1
#    GasShortTerm_Dashboard   at logon     -> run_dashboard.ps1 (port 8501)
#  The spread signal stays manual (needs the 09:00-09:30 prices typed in):
#  run spread_signal.ps1 after 09:30 each morning.
# ============================================================================
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition

# -- daily data update at 07:45 (ecop weather run is in by then) --------------
Register-ScheduledTask `
    -TaskName 'GasShortTerm_DataUpdate' `
    -Action   (New-ScheduledTaskAction -Execute 'powershell.exe' `
                 -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\update_data.ps1`"") `
    -Trigger  (New-ScheduledTaskTrigger -Daily -At '07:45') `
    -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -StartWhenAvailable) `
    -RunLevel Highest -Force
Write-Host "Registered: GasShortTerm_DataUpdate (daily 07:45)"

# -- dashboard at logon -------------------------------------------------------
Register-ScheduledTask `
    -TaskName 'GasShortTerm_Dashboard' `
    -Action   (New-ScheduledTaskAction -Execute 'powershell.exe' `
                 -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_dashboard.ps1`"") `
    -Trigger  (New-ScheduledTaskTrigger -AtLogOn) `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) `
    -RunLevel Highest -Force
Write-Host "Registered: GasShortTerm_Dashboard (at logon, http://localhost:8501)"
Write-Host ""
Write-Host "Run now:  Start-ScheduledTask -TaskName 'GasShortTerm_DataUpdate'"
