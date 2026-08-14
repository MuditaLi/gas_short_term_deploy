# ============================================================================
#  Copy the latest pipeline outputs into data\ and push to GitHub, so the
#  hosted dashboard picks them up. Now a wrapper around run_day.py, which
#  checks each file's data dates before copying and holds back stale ones
#  rather than stamping them as fresh.
#  Every stage of run_day.py publishes, so this is rarely needed on its own.
# ============================================================================
& (Join-Path $PSScriptRoot 'run_day.ps1') publish @args
exit $LASTEXITCODE
