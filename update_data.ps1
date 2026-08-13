# ============================================================================
#  Gas Short-Term Outlook & Signals - daily data update
#  1. daily_storage_forecast\main.py        (S&D pipeline -> snd_*.csv)
#  2. quant_strats\DA_M1\2-storage_flow_forecast.py  (flow model forecast)
#  Logs to logs\update_YYYYMMDD_HHMM.log. Safe to re-run any time.
#  NOTE: the spread signal (3-spread_forecast.py) is NOT here - it needs the
#  09:00-09:30 prices typed in; use spread_signal.ps1 after 09:30.
# ============================================================================
# repo root = parent of this deploy folder (standard sibling layout);
# override with the GAS_GITHUB_ROOT environment variable if needed
$github = if ($env:GAS_GITHUB_ROOT) { $env:GAS_GITHUB_ROOT } else { Split-Path -Parent $PSScriptRoot }
$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ('update_{0:yyyyMMdd_HHmm}.log' -f (Get-Date))

function Run-Step($name, $script, $py = 'python') {
    $stamp = Get-Date -Format 'HH:mm:ss'
    Add-Content $log "`n=== [$stamp] $name ==="
    Write-Host "=== $name ==="
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    $p = Start-Process -FilePath $py -ArgumentList "`"$script`"" `
         -Wait -PassThru -NoNewWindow `
         -RedirectStandardOutput $out -RedirectStandardError $err
    Get-Content $out, $err | Add-Content $log
    Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) {
        Add-Content $log "FAILED: $name (exit $($p.ExitCode))"
        Write-Host "FAILED: $name (exit $($p.ExitCode)) - see $log"
        return $false
    }
    Write-Host "OK: $name"
    return $true
}

$ok1 = Run-Step 'S&D pipeline (daily_storage_forecast)' "$github\daily_storage_forecast\main.py"

# DA_M1 scripts run in their own venv when present (unambiguous deps)
$dam1py = Join-Path $github 'quant_strats\DA_M1\.venv\Scripts\python.exe'
if (-not (Test-Path $dam1py)) { $dam1py = 'python' }
$ok2 = Run-Step 'DA_M1 flow forecast'                   "$github\quant_strats\DA_M1\2-storage_flow_forecast.py" $dam1py

Add-Content $log ("`n=== done {0:yyyy-MM-dd HH:mm} | snd={1} flow={2} ===" -f (Get-Date), $ok1, $ok2)
Write-Host "log -> $log"
if (-not ($ok1 -and $ok2)) { exit 1 }
