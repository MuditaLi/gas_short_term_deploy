# gas_short_term_deploy

Deployment folder for the **Gas Short-Term Outlook & Signals** dashboard and
the daily data updates behind it. Nothing lives here except runners — code and
data stay in their own repos:

- `daily_storage_forecast\` — S&D pipeline (`main.py`) + the dashboard (`snd_dashboard.py`)
- `quant_strats\DA_M1\` — flow-model forecast (script 2) + spread signal (script 3)

## Scripts

| script | what it does | when |
|---|---|---|
| `update_data.ps1` | runs the S&D pipeline, then the DA_M1 flow forecast; logs to `logs\` | daily ~07:45 (scheduled) |
| `spread_signal.ps1` | prompts for the two 09:00-09:30 prices, runs the spread signal | manually, after 09:30 |
| `run_dashboard.ps1` | serves the dashboard at http://localhost:8501 | at logon (scheduled) or manually |
| `schedule_tasks.ps1` | registers the two scheduled tasks (run once, as Administrator) | one-time setup |

## Morning routine

1. 07:45 — data update runs by itself (check `logs\` if the dashboard warns of stale data).
2. After 09:30 — run `spread_signal.ps1`, type the two prices from the Trayport screen.
3. Dashboard at http://localhost:8501 refreshes itself (signal within ~2 min, data on reload).

## Maintenance

- **Monthly retrain** (order matters): `train_storage_model.ipynb` first, then the
  final-model + export cells in `spread_forecast_pipe.ipynb`. The daily scripts warn
  when a retrain is due (>35 days) or overdue (>60 days). See `DA_M1\README.md`.
- Logs accumulate in `logs\` — prune occasionally.
- Dependencies: `pip install -r daily_storage_forecast\requirements.txt` plus
  `streamlit plotly` (dashboard) — see the repos' own requirements files.
