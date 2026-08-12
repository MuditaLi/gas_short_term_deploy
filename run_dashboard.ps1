# ============================================================================
#  Gas Short-Term Outlook & Signals - start the dashboard (local)
#  Serves http://localhost:8501. Same app as the hosted one: reads data\.
#  Run publish_data.ps1 (or spread_signal.ps1) first so data\ is fresh.
#  Leave the window open; Ctrl+C stops it.
# ============================================================================
streamlit run (Join-Path $PSScriptRoot 'dashboard.py') `
    --server.port 8501 --server.headless true
