# ============================================================================
#  Gas Short-Term Outlook & Signals - morning spread signal (run after 09:30)
#  Prompts for the two 09:00-09:30 prices (the only manual inputs),
#  then runs 3-spread_forecast.py and logs the signal.
# ============================================================================
# repo root = parent of this deploy folder (standard sibling layout);
# override with the GAS_GITHUB_ROOT environment variable if needed
$github = if ($env:GAS_GITHUB_ROOT) { $env:GAS_GITHUB_ROOT } else { Split-Path -Parent $PSScriptRoot }

# prefer the DA_M1 venv (unambiguous deps); fall back to PATH python
$dam1 = Join-Path $github 'quant_strats\DA_M1'
$py = Join-Path $dam1 '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

$da = Read-Host 'DA  09:00-09:30 price (EUR/MWh)'
$m1 = Read-Host 'M1  09:00-09:30 price (EUR/MWh)'

& $py "$dam1\3-spread_forecast.py" --da $da --m1 $m1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# push fresh data + signal to GitHub for the hosted dashboard
& (Join-Path $PSScriptRoot 'publish_data.ps1')
