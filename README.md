# gas_short_term_deploy

Deployment repo for the **Gas Short-Term Outlook & Signals** dashboard.
Self-contained: `dashboard.py` reads only the repo-local `data/` folder, so the
same app runs locally and on Streamlit Community Cloud. **Keep this repo
PRIVATE — it carries desk forecasts and trading signals.**

The pipelines that generate the data live in sibling repos (not needed by the
hosted dashboard, only by the publishing machine):

- `daily_storage_forecast\` — S&D pipeline (`main.py`)
- `quant_strats\DA_M1\` — flow-model forecast (script 2) + spread signal (script 3)

## Scripts (publishing machine)

| script | what it does | when |
|---|---|---|
| `update_data.ps1` | runs the S&D pipeline + DA_M1 flow forecast; logs to `logs\` | daily ~07:45 (scheduled) |
| `spread_signal.ps1` | prompts for the two 09:00-09:30 prices, runs the spread signal, then **publishes data to GitHub** | manually, after 09:30 |
| `publish_data.ps1` | copies fresh CSVs into `data\`, commits, pushes | auto (from spread_signal) or manual |
| `run_dashboard.ps1` | serves the dashboard locally at http://localhost:8501 | optional |
| `schedule_tasks.ps1` | registers scheduled tasks (run once, as Administrator) | one-time setup |

Repo root is derived from this folder's location (standard sibling layout);
override with the `GAS_GITHUB_ROOT` environment variable.

## Hosted dashboard (Streamlit Community Cloud)

1. Push this repo to GitHub (**private**).
2. share.streamlit.io -> New app -> pick this repo, `dashboard.py`, branch master.
3. Done — every `publish_data.ps1` push updates the hosted app automatically.

## Morning routine

1. 07:45 — data update runs by itself (check `logs\` on stale-data warnings).
2. After 09:30 — run `spread_signal.ps1`: type the two prices; it computes the
   signal AND publishes everything to GitHub in one go.
3. Dashboard: hosted URL (or http://localhost:8501 via `run_dashboard.ps1`).

## Maintenance

- **Monthly retrain** (order matters): `train_storage_model.ipynb` first, then
  the export cells in `spread_forecast_pipe.ipynb`. The daily scripts warn when
  a retrain is due. See `quant_strats\DA_M1\README.md`.
- `data/` is committed by design (the hosted app needs it); `logs/` is not.
