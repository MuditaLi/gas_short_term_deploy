# ============================================================================
#  Gas Short-Term Outlook & Signals - start the dashboard
#  Serves http://localhost:8501 (and on the machine's network IP).
#  Leave the window open; Ctrl+C stops it.
# ============================================================================
# repo root = parent of this deploy folder (standard sibling layout);
# override with the GAS_GITHUB_ROOT environment variable if needed
$github = if ($env:GAS_GITHUB_ROOT) { $env:GAS_GITHUB_ROOT } else { Split-Path -Parent $PSScriptRoot }
streamlit run "$github\daily_storage_forecast\snd_dashboard.py" `
    --server.port 8501 --server.headless true
