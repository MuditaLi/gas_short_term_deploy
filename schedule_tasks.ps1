# ============================================================================
#  Windows Task Scheduler setup - run once (as Administrator) to register:
#    GasShortTerm_Morning      daily 07:45  S&D + flow forecast, then publish
#    GasShortTerm_SignalCheck  daily 09:35  toast if today's signal is missing
#    GasShortTerm_Backfill     daily 10:15  yesterday's true 09:00-09:30 vwap
#    GasShortTerm_Dashboard    at logon     run_dashboard.ps1 (port 8501)
#
#  The 09:00-09:30 prices stay manual - Trayport embargoes intraday data for
#  24h, so they cannot be fetched. Enter them in the dashboard after 09:30;
#  SignalCheck nags at 09:35 if they are still outstanding.
#
#  Backfill runs at 10:15 because yesterday's 09:00-09:30 window only clears
#  the 24h embargo at 09:30 today.
# ============================================================================
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Register-GasTask($name, $stage, $trigger, $limitMinutes) {
    Register-ScheduledTask `
        -TaskName $name `
        -Action   (New-ScheduledTaskAction -Execute 'powershell.exe' `
                     -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_day.ps1`" $stage") `
        -Trigger  $trigger `
        -Settings (New-ScheduledTaskSettingsSet `
                     -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMinutes) `
                     -MultipleInstances IgnoreNew -StartWhenAvailable) `
        -RunLevel Highest -Force | Out-Null
    Write-Host "Registered: $name"
}

# -- the old single task is replaced by the staged ones ----------------------
try {
    Unregister-ScheduledTask -TaskName 'GasShortTerm_DataUpdate' -Confirm:$false -ErrorAction Stop
    Write-Host 'Removed: GasShortTerm_DataUpdate (replaced by GasShortTerm_Morning)'
} catch {}

Register-GasTask 'GasShortTerm_Morning'     'morning'      (New-ScheduledTaskTrigger -Daily -At '07:45') 60
Register-GasTask 'GasShortTerm_SignalCheck' 'check-signal' (New-ScheduledTaskTrigger -Daily -At '09:35') 5
Register-GasTask 'GasShortTerm_Backfill'    'backfill'     (New-ScheduledTaskTrigger -Daily -At '10:15') 30

# -- dashboard at logon -------------------------------------------------------
Register-ScheduledTask `
    -TaskName 'GasShortTerm_Dashboard' `
    -Action   (New-ScheduledTaskAction -Execute 'powershell.exe' `
                 -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_dashboard.ps1`"") `
    -Trigger  (New-ScheduledTaskTrigger -AtLogOn) `
    -Settings (New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable) `
    -RunLevel Highest -Force | Out-Null
Write-Host 'Registered: GasShortTerm_Dashboard (at logon, http://localhost:8501)'

Write-Host ''
Write-Host "Run now:  Start-ScheduledTask -TaskName 'GasShortTerm_Morning'"
Write-Host "Prices:   http://localhost:8501 after 09:30"
