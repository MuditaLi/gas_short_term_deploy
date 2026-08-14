# ============================================================================
#  Terminal route to the morning spread signal (run after 09:30).
#  The dashboard at http://localhost:8501 does the same thing with a form -
#  this stays for when you would rather not leave the shell.
#  Prompts for the two 09:00-09:30 prices, then runs the signal and publishes.
# ============================================================================
$da = Read-Host 'DA  09:00-09:30 price (EUR/MWh)'
$m1 = Read-Host 'M1  09:00-09:30 price (EUR/MWh)'

& (Join-Path $PSScriptRoot 'run_day.ps1') signal --da $da --m1 $m1
exit $LASTEXITCODE
