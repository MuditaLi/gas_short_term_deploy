# ============================================================================
#  Gas Short-Term Outlook & Signals - morning spread signal (run after 09:30)
#  Prompts for the two 09:00-09:30 prices (the only manual inputs),
#  then runs 3-spread_forecast.py and logs the signal.
# ============================================================================
# repo root = parent of this deploy folder (standard sibling layout);
# override with the GAS_GITHUB_ROOT environment variable if needed
$github = if ($env:GAS_GITHUB_ROOT) { $env:GAS_GITHUB_ROOT } else { Split-Path -Parent $PSScriptRoot }

$da = Read-Host 'DA  09:00-09:30 price (EUR/MWh)'
$m1 = Read-Host 'M1  09:00-09:30 price (EUR/MWh)'

python "$github\quant_strats\DA_M1\3-spread_forecast.py" --da $da --m1 $m1
