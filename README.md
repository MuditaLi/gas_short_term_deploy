# gas_short_term_deploy

Deployment repo for the **Gas Short-Term Outlook & Signals** dashboard.
Self-contained: `dashboard.py` reads only the repo-local `data/` folder, so the
same app runs locally and on Streamlit Community Cloud. **Keep this repo
PRIVATE — it carries desk forecasts and trading signals.**

The pipelines that generate the data live in sibling repos (not needed by the
hosted dashboard, only by the publishing machine):

- `daily_storage_forecast\` — S&D pipeline (`main.py`)
- `quant_strats\DA_M1\` — flow-model forecast (script 2) + spread signal (script 3)

## Running it (publishing machine)

Everything goes through one entry point, `run_day.py` (`run_day.ps1` is the
launcher Task Scheduler calls):

| stage | what it does | when |
|---|---|---|
| `morning` | S&D pipeline + DA_M1 flow forecast, then publish | daily 07:45 (scheduled) |
| `signal` | spread signal from the 09:00-09:30 prices, then publish | after 09:30, from the dashboard |
| `backfill` | recomputes yesterday's signal from its *true* 09:00-09:30 vwap | daily 10:15 (scheduled) |
| `publish` | validates and copies outputs into `data\`, commits, pushes | inside every stage; rarely needed alone |
| `check-signal` | desktop notification if today's signal is still missing | daily 09:35 (scheduled) |

```powershell
.\run_day.ps1 morning              # or: Start-ScheduledTask GasShortTerm_Morning
.\run_day.ps1 signal --da 60.42 --m1 60.66
.\run_day.ps1 backfill --asof 2026-08-13
```

Switches: `--force` (rerun steps whose outputs are already fresh), `--no-push`
(publish to `data\` without pushing), `--allow-stale` (publish files that fail
their freshness check — escape hatch, normally leave alone).

Other scripts: `run_dashboard.ps1` serves the dashboard at
http://localhost:8501; `schedule_tasks.ps1` registers the scheduled tasks (run
once, as Administrator). `update_data.ps1`, `spread_signal.ps1` and
`publish_data.ps1` still work — they are thin wrappers around the stages above.

Repo root is derived from this folder's location (standard sibling layout);
override with the `GAS_GITHUB_ROOT` environment variable. `GAS_PYTHON` pins the
interpreter; each pipeline uses its own `.venv` automatically when it has one.

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
- **Failures notify** (desktop toast, falling back to `msg`), instead of only
  appearing in `logs\`.

## Hosted dashboard (Streamlit Community Cloud)

1. Push this repo to GitHub (**private**).
2. share.streamlit.io -> New app -> pick this repo, `dashboard.py`, branch master.
3. Done — every publish pushes and updates the hosted app automatically.

The run controls (price entry, the buttons) only appear when the pipelines are
checked out beside this repo. On the hosted app they are hidden and the page is
read-only.

## Morning routine

1. 07:45 — S&D + flow forecast run and publish by themselves. Nothing to do
   unless a toast says otherwise; the dashboard shows the per-stage status.
2. After 09:30 — open the dashboard and type the two 09:00-09:30 prices into
   the form at the top. That runs the signal and publishes in one go. (A toast
   at 09:35 reminds you if it is still outstanding; `spread_signal.ps1` does the
   same thing from a terminal.)
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
