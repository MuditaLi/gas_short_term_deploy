# ============================================================================
#  Kept for muscle memory: the morning update now lives in run_day.py.
#  Runs the S&D pipeline + the DA_M1 flow forecast, then publishes to data\.
#  Unlike the old version the two forecasts are independent (one failing no
#  longer skips the other) and the dashboard is published either way.
# ============================================================================
& (Join-Path $PSScriptRoot 'run_day.ps1') morning @args
exit $LASTEXITCODE
