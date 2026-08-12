# ============================================================================
#  Copy the latest pipeline outputs into data\ and push to GitHub, so the
#  hosted dashboard (Streamlit Cloud) picks them up.
#  Called automatically at the end of spread_signal.ps1; safe to run manually.
# ============================================================================
# repo root = parent of this deploy folder (standard sibling layout);
# override with the GAS_GITHUB_ROOT environment variable if needed
$github = if ($env:GAS_GITHUB_ROOT) { $env:GAS_GITHUB_ROOT } else { Split-Path -Parent $PSScriptRoot }
$data = Join-Path $PSScriptRoot 'data'
New-Item -ItemType Directory -Force $data | Out-Null

$snd = Join-Path $github 'daily_storage_forecast\outputs'
$dam = Join-Path $github 'quant_strats\DA_M1\outputs'

Copy-Item "$snd\snd_de.csv", "$snd\snd_nl.csv", "$snd\snd_uk.csv", "$snd\country_balance.csv" $data -Force
Copy-Item "$dam\storage_flow_forecast.csv", "$dam\spread_signal_log.csv" $data -Force
(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Out-File -Encoding utf8 (Join-Path $data '_updated.txt')

Set-Location $PSScriptRoot
git add data
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host 'no data changes to publish'
    exit 0
}
git commit -m ("data {0:yyyy-MM-dd HH:mm}" -f (Get-Date)) | Out-Null
git push
if ($LASTEXITCODE -ne 0) {
    Write-Host 'PUSH FAILED - data committed locally, push manually (git push)'
    exit 1
}
Write-Host 'published -> GitHub (hosted dashboard updates on next rerun)'
