# gas_short_term_deploy

Deployment repo for the **Gas Short-Term Outlook & Signals** dashboard.
Self-contained: `dashboard.py` reads only the repo-local `data/` folder, so the
same app runs locally and on Streamlit Community Cloud. **Keep this repo
PRIVATE — it carries desk forecasts and trading signals.**

The pipelines that generate the data live in sibling repos (not needed by the
hosted dashboard, only by the publishing machine):

- `daily_storage_forecast\` — S&D pipeline (`main.py`)
- `quant_strats\DA_M1\` — flow-model forecast (script 2) + spread signal (script 3)

## Running it (scheduler host, e.g. Databricks)

Everything goes through one entry point, `run_day.py`; each stage is one
scheduled job:

| stage | what it does | when |
|---|---|---|
| `morning` | S&D pipeline + DA_M1 flow forecast, then publish | daily 07:45 |
| `signal` | spread signal from the 09:00-09:30 prices, then publish | after 09:30 |
| `backfill` | recomputes yesterday's signal from its *true* 09:00-09:30 vwap | daily 10:15 (not before 10:00 — Trayport embargo) |
| `publish` | validates and copies outputs into `data\`, commits, pushes | inside every stage; rarely needed alone |
| `check-signal` | exits non-zero if today's signal is still missing | daily 09:35 |

```
python run_day.py morning
python run_day.py signal --da 60.42 --m1 60.66
python run_day.py backfill --asof 2026-08-13
```

Switches: `--force` (rerun steps whose outputs are already fresh), `--no-push`
(publish to `data\` without pushing), `--allow-stale` (publish files that fail
their freshness check — escape hatch, normally leave alone).
`streamlit run dashboard.py` serves the page locally.

Repo root is derived from this folder's location (standard sibling layout);
override with the `GAS_GITHUB_ROOT` environment variable. Each pipeline uses
its own `.venv` automatically when it has one, else the current interpreter.
Publish commits `data/` and runs `git push`, so the host needs a git credential
for this repo.

### What the runner guarantees

- **Every stage publishes**, so the dashboard is never stale just because the
  spread signal did not run that day.
- **Nothing stale is published.** Each file must have been rebuilt today *and*
  contain a row for tomorrow before it is copied. Files that fail are held
  back, the previous good data stays in place, and `data\status.json` records
  why — the dashboard shows it in red. `_updated.txt` is only stamped on a
  clean publish, so it can never vouch for data that was held back.
- **The two forecasts are independent** (the flow script refreshes its own
  MetDesk inputs), so one failing no longer skips the other.
- **Reruns are cheap.** A step whose outputs are already fresh is skipped, so
  recovering from a mid-morning failure does not repeat the ~20 min MetDesk
  fetch.
- **Failures are loud.** A failed stage prints a `[notify]` line and exits
  non-zero, so the scheduler flags the run; `logs\` keeps the full output.

## Hosted dashboard (Streamlit Community Cloud)

1. Push this repo to GitHub (**private**).
2. share.streamlit.io -> New app -> pick this repo, `dashboard.py`, branch master.
3. Done — every publish pushes and updates the hosted app automatically.

The page is read-only: forecasts, the latest logged signal and the pipeline
status. It never runs anything; the scheduler does, through `run_day.py`.
Publish also exports `price_history.csv` (DA/M1 17:00-17:30 close VWAPs, the
model's price input) and `spread_model_params.csv` into `data/`.

Publish also exports two pieces of S&D context that the assembled tables
cannot carry (best-effort, never blocks the forecasts):

- `regas_lng_alerts.csv` — the regas step's LNG shock check (Kpler cargo
  arrivals through the calibrated release kernel vs the recent-level anchor)
  for DE/NL/UK, newest run only. `alert=True` days are shown as a warning and
  an `LNG ⚠` mark on the country chart; the regas forecast itself is **not**
  adjusted by the pipeline (alert-only by design). An empty file means the
  check did not run (Kpler unreachable) and the page says so.
- `ldz_models.csv` — LDZ demand under both weather models. The S&D tables use
  ecop; the page adds `LDZ (gfsop)` and `Balance with gfsop LDZ` rows and a
  dashed alternative balance line, so the weather-model dependence is visible.

## Morning routine

1. 07:45 — S&D + flow forecast run and publish by themselves. Nothing to do
   unless the job fails; the dashboard shows the per-stage status.
2. After 09:30 — the `signal` job runs `run_day.py signal --da … --m1 …` with
   the two 09:00-09:30 VWAPs and publishes. The 09:35 `check-signal` job fails
   if the signal is still outstanding. (Automating the price fetch lives in
   `quant_strats\DA_M1\3-spread_forecast.py`, not here — see its docstring.)
3. 10:15 — yesterday's signal is recomputed from its true 09:00-09:30 vwap into
   `spread_signal_backfill.csv`, with no action from you.

Trayport embargoes intraday data for 24 hours (hourly bars included — verified,
not just minute bars), so those two prices genuinely cannot be fetched at 09:30
and stay the one manual input of the day. Comparing `spread_signal_log.csv`
(what was tradeable, screen prices) with `spread_signal_backfill.csv` (the true
window) measures what the screen-price entry costs.

## Maintenance

- **Monthly retrain** (order matters): `train_storage_model.ipynb` first, then
  the export cells in `spread_forecast_pipe.ipynb`. The daily scripts warn when
  a retrain is due. See `quant_strats\DA_M1\README.md`.
- `data/` is committed by design (the hosted app needs it); `logs/` is not.
