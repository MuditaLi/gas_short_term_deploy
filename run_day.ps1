# ============================================================================
#  Launcher for run_day.py - this is what Task Scheduler calls.
#
#    .\run_day.ps1 morning                 S&D + flow forecast, then publish
#    .\run_day.ps1 signal --da 60.42 --m1 60.66
#    .\run_day.ps1 backfill                yesterday's true 09:00-09:30 vwap
#    .\run_day.ps1 publish
#    .\run_day.ps1 check-signal            toast if today's signal is missing
#
#  Extra switches (--force, --no-push, --allow-stale) pass straight through.
#  Set GAS_PYTHON to pin an interpreter, GAS_GITHUB_ROOT to move the repos.
# ============================================================================
param(
    [Parameter(Position = 0)]
    [ValidateSet('morning', 'signal', 'backfill', 'publish', 'check-signal')]
    [string]$Stage = 'morning',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$py = if ($env:GAS_PYTHON) { $env:GAS_PYTHON } else { 'python' }

$argsList = @((Join-Path $PSScriptRoot 'run_day.py'), $Stage)
if ($Rest) { $argsList += $Rest }

& $py @argsList
exit $LASTEXITCODE
