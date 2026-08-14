"""
Gas Short-Term Outlook & Signals - daily runner (single entry point).

Stages
    morning       daily_storage_forecast\\main.py  +  DA_M1\\2-storage_flow_forecast.py, then publish
    signal        DA_M1\\3-spread_forecast.py --da/--m1, then publish   (the 09:00-09:30 prices)
    backfill      DA_M1\\3-spread_forecast.py --asof <day>, then publish
    publish       copy validated outputs into data\\ and push to GitHub
    check-signal  notify if today's signal is still missing

Why it is built this way
    * Every stage ends in publish, so the dashboard is never hostage to a stage
      that did not run (previously only the manual spread signal published).
    * Publish validates each file's *data dates* and its mtime before copying,
      and refuses stale files, so a failed pipeline can no longer be published
      as fresh. data\\status.json records exactly what was published and what
      was blocked; the dashboard reads it.
    * The S&D pipeline and the flow forecast are independent (the flow script
      refreshes its own MetDesk inputs), so one failing no longer skips the
      other.
    * Steps whose outputs are already fresh are skipped, so a rerun after a
      failure costs seconds instead of repeating the ~20 min MetDesk fetch.
      --force reruns them anyway.

Usage
    python run_day.py morning
    python run_day.py signal --da 60.42 --m1 60.66
    python run_day.py backfill                  # yesterday (or --asof 2026-08-13)
    python run_day.py publish
    python run_day.py check-signal

The sibling-repo root is the parent of this folder; override with the
GAS_GITHUB_ROOT environment variable.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from notify import notify

REPO   = Path(__file__).resolve().parent
GITHUB = Path(os.environ.get('GAS_GITHUB_ROOT') or REPO.parent)
SND    = GITHUB / 'daily_storage_forecast'
DAM1   = GITHUB / 'quant_strats' / 'DA_M1'
DATA   = REPO / 'data'
LOGS   = REPO / 'logs'
STATUS = DATA / 'status.json'

SND_FILES     = ['snd_de.csv', 'snd_nl.csv', 'snd_uk.csv', 'country_balance.csv']
FLOW_FILE     = 'storage_flow_forecast.csv'
SIGNAL_FILE   = 'spread_signal_log.csv'
BACKFILL_FILE = 'spread_signal_backfill.csv'

_logf = None

# The pipelines print box-drawing characters. When our own stdout is a pipe
# (Task Scheduler, PowerShell capture, the dashboard subprocess) it defaults to
# cp1252 here and relaying those lines would raise UnicodeEncodeError mid-run.
# The log file is opened as utf-8, so only the console view degrades.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except Exception:
        pass


# ---------------------------------------------------------------- logging ----

def say(msg=''):
    print(msg, flush=True)
    if _logf is not None:
        _logf.write(msg + '\n')
        _logf.flush()


def open_log(stage):
    global _logf
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f'{stage}_{datetime.now():%Y%m%d_%H%M}.log'
    _logf = open(path, 'a', encoding='utf-8')
    say(f"=== {stage} | {datetime.now():%Y-%m-%d %H:%M:%S} | {socket.gethostname()} ===")
    return path


# ------------------------------------------------------------- freshness ----

def today():
    return pd.Timestamp(datetime.today().date())


def dates_in(path: Path):
    """The 'date' column of a CSV as timestamps, or None if unreadable."""
    try:
        col = pd.read_csv(path, usecols=['date'])['date']
        return pd.to_datetime(col, errors='coerce').dropna()
    except Exception:
        return None


def covers(path: Path, day) -> bool:
    d = dates_in(path)
    return d is not None and bool((d == day).any())


def latest_date(path: Path):
    d = dates_in(path)
    return None if d is None or d.empty else d.max()


def written_today(path: Path) -> bool:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date() == datetime.today().date()
    except OSError:
        return False


def fresh(path: Path, must_cover=None) -> bool:
    """Regenerated today and (optionally) carrying a row for `must_cover`.

    Both halves matter: the forecast horizon runs ~10 days out, so yesterday's
    file still 'covers tomorrow' - only the mtime proves it was rebuilt today.
    """
    if not path.exists() or not written_today(path):
        return False
    return must_cover is None or covers(path, must_cover)


# ------------------------------------------------------------- execution ----

def python_for(project: Path) -> str:
    """A project's own venv when it has one (unambiguous deps), else ours."""
    venv = project / '.venv' / 'Scripts' / 'python.exe'
    return str(venv) if venv.exists() else sys.executable


def run_script(project: Path, script: str, args=()) -> int:
    """Run a script in its own project, streaming output to console + log.

    PYTHONIOENCODING is forced: the pipelines print box-drawing characters, and
    a child writing to a pipe defaults to cp1252 here, which raises
    UnicodeEncodeError mid-run. Unbuffered so the stream stays live.
    """
    cmd = [python_for(project), str(project / script), *[str(a) for a in args]]
    say(f"$ {' '.join(cmd)}")
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    proc = subprocess.Popen(cmd, cwd=str(project), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, encoding='utf-8', errors='replace')
    with proc:
        for line in proc.stdout:
            say(line.rstrip('\n'))
    return proc.returncode


@dataclass
class Step:
    key: str
    title: str
    project: Path
    script: str

    def is_fresh(self) -> bool:
        raise NotImplementedError

    def run(self, force=False) -> tuple:
        """Returns (ok, detail). Verifies the contract after running, so a
        step that exits 0 without writing its outputs still counts as failed."""
        if not force and self.is_fresh():
            say(f"-- skip {self.title}: outputs already fresh")
            return True, 'skipped (already fresh)'
        say(f"\n== {self.title} ==")
        t0 = time.time()
        rc = run_script(self.project, self.script)
        mins = (time.time() - t0) / 60
        if rc != 0:
            say(f"FAILED {self.title} (exit {rc}) after {mins:.1f} min")
            return False, f'exit {rc}'
        if not self.is_fresh():
            say(f"FAILED {self.title}: exited 0 but outputs are not fresh")
            return False, 'exit 0 but outputs not fresh'
        say(f"OK {self.title} ({mins:.1f} min)")
        return True, f'ok in {mins:.1f} min'


class SndStep(Step):
    def is_fresh(self):
        tmr = today() + pd.Timedelta(days=1)
        return all(fresh(SND / 'outputs' / f, tmr) for f in SND_FILES)


class FlowStep(Step):
    def is_fresh(self):
        path = DAM1 / 'outputs' / FLOW_FILE
        return fresh(path, today()) and covers(path, today() + pd.Timedelta(days=1))


SND_STEP  = SndStep('snd',  'S&D pipeline (daily_storage_forecast)', SND,  'main.py')
FLOW_STEP = FlowStep('flow', 'DA_M1 storage flow forecast',          DAM1, '2-storage_flow_forecast.py')


# ----------------------------------------------------------------- status ----

def load_status() -> dict:
    try:
        return json.loads(STATUS.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_status(**patch):
    """Merge into status.json so stages not run now keep their last result."""
    st = load_status()
    for key, value in patch.items():
        if key in ('stages', 'files') and isinstance(value, dict):
            st.setdefault(key, {}).update(value)
        else:
            st[key] = value
    st['updated'] = f'{datetime.now():%Y-%m-%d %H:%M:%S}'
    st['host'] = socket.gethostname()
    DATA.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(st, indent=2), encoding='utf-8')


def record_stage(key, ok, detail=''):
    save_status(stages={key: {
        'status': 'ok' if ok else 'failed',
        'detail': detail,
        'finished': f'{datetime.now():%Y-%m-%d %H:%M}',
    }})


# ---------------------------------------------------------------- publish ----

def dedup_signal_log(path: Path) -> int:
    """Drop rows identical in every field but 'issued' (keeping the earliest).

    3-spread_forecast.py appends unconditionally, so re-running it without
    changing the prices used to leave exact duplicates in the log - harmless
    for the dashboard, but it double-counts in any hit-rate calculation.
    A genuine re-run with different prices differs in da_am/m1_am and is kept.
    """
    try:
        df = pd.read_csv(path)
    except Exception:
        return 0
    keys = [c for c in df.columns if c != 'issued']
    if not keys:
        return 0
    before = len(df)
    df = df.drop_duplicates(subset=keys, keep='first')
    dropped = before - len(df)
    if dropped:
        df.to_csv(path, index=False)
    return dropped


def publish(allow_stale=False, push=True) -> bool:
    """Copy validated outputs into data\\ and push. Stale files are not copied."""
    say('\n== publish ==')
    DATA.mkdir(parents=True, exist_ok=True)
    tmr = today() + pd.Timedelta(days=1)

    # (name, source dir, date the file must cover, gates the publish)
    contracts = [(f, SND / 'outputs', tmr, True) for f in SND_FILES]
    contracts += [
        (FLOW_FILE,     DAM1 / 'outputs', tmr,  True),
        (SIGNAL_FILE,   DAM1 / 'outputs', None, False),
        (BACKFILL_FILE, DAM1 / 'outputs', None, False),
    ]

    files, blocked = {}, []
    for name, src_dir, must_cover, required in contracts:
        src = src_dir / name
        # status.json is committed, so it records which pipeline a file came
        # from but never the full internal path
        info = {'source': src_dir.parent.name}
        if not src.exists():
            info['published'] = False
            info['reason'] = 'missing'
            if required:
                blocked.append(f'{name}: missing')
            files[name] = info
            continue

        last = latest_date(src)
        info['data_through'] = None if last is None else f'{last:%Y-%m-%d}'
        info['built'] = f'{datetime.fromtimestamp(src.stat().st_mtime):%Y-%m-%d %H:%M}'

        reason = None
        if required:
            if not written_today(src):
                reason = f"not rebuilt today (last built {info['built']})"
            elif must_cover is not None and not covers(src, must_cover):
                reason = f'no row for {must_cover:%Y-%m-%d}'

        if reason and not allow_stale:
            info['published'] = False
            info['reason'] = reason
            blocked.append(f'{name}: {reason}')
            say(f'  BLOCKED {name} - {reason}')
        else:
            if name == SIGNAL_FILE:
                dropped = dedup_signal_log(src)
                if dropped:
                    say(f'  deduped {dropped} repeated row(s) in {name}')
            shutil.copyfile(src, DATA / name)
            info['published'] = True
            if reason:
                info['reason'] = f'stale, forced: {reason}'
            say(f"  {name} -> data\\  (data through {info['data_through']})")
        files[name] = info

    # signal freshness is reported, never gated: the morning publish runs
    # hours before the 09:30 signal exists
    sig = {}
    sig_path = DATA / SIGNAL_FILE
    if sig_path.exists():
        try:
            log = pd.read_csv(sig_path, parse_dates=['date'])
            row = log[log['date'] == log['date'].max()].sort_values('issued').iloc[-1]
            sig = {'date': f"{row['date']:%Y-%m-%d}", 'issued': str(row['issued']),
                   'is_today': row['date'].date() == datetime.today().date()}
        except Exception as exc:
            sig = {'error': str(exc)}

    save_status(files=files, blocked=blocked, signal=sig)

    if blocked:
        say(f'PUBLISH INCOMPLETE - {len(blocked)} file(s) held back, previous data kept')
    else:
        # only stamped on a clean publish, so it can never claim freshness for
        # data that was held back (kept for older dashboard builds)
        (DATA / '_updated.txt').write_text(f'{datetime.now():%Y-%m-%d %H:%M:%S}', encoding='utf-8')

    pushed = git_publish() if push else True
    return not blocked and pushed


def git_publish() -> bool:
    """Commit data\\ and push, so the hosted dashboard picks it up."""
    def git(*args):
        return subprocess.run(['git', *args], cwd=str(REPO),
                              capture_output=True, text=True)

    git('add', 'data')
    if git('diff', '--cached', '--quiet').returncode == 0:
        say('  git: no data changes to publish')
        return True
    git('commit', '-m', f'data {datetime.now():%Y-%m-%d %H:%M}')
    done = git('push')
    if done.returncode != 0:
        say(f'  git: PUSH FAILED - committed locally, push manually\n{done.stderr.strip()}')
        return False
    say('  git: pushed -> hosted dashboard')
    return True


# ------------------------------------------------------------------ stages ---

def stage_morning(force=False, push=True, allow_stale=False) -> bool:
    # independent steps: the flow forecast refreshes its own MetDesk inputs and
    # does not read the S&D outputs, so a failure in one must not skip the other
    ok_snd, d_snd = SND_STEP.run(force)
    record_stage('snd', ok_snd, d_snd)
    ok_flow, d_flow = FLOW_STEP.run(force)
    record_stage('flow', ok_flow, d_flow)

    ok_pub = publish(allow_stale=allow_stale, push=push)
    record_stage('publish', ok_pub, 'clean' if ok_pub else 'incomplete - see blocked')

    if not (ok_snd and ok_flow and ok_pub):
        failed = [n for n, ok in (('S&D', ok_snd), ('flow', ok_flow), ('publish', ok_pub)) if not ok]
        notify('Gas morning update failed', f"{', '.join(failed)} - see {LOGS.name}\\ and the dashboard")
    return ok_snd and ok_flow and ok_pub


def stage_signal(da, m1, push=True, allow_stale=False) -> bool:
    if da is None or m1 is None:
        say('ERROR: signal needs --da and --m1 (the 09:00-09:30 vwaps)')
        return False
    say(f'\n== DA-M1 spread signal (DA {da} / M1 {m1}) ==')
    rc = run_script(DAM1, '3-spread_forecast.py', ['--da', da, '--m1', m1])
    ok = rc == 0 and covers(DAM1 / 'outputs' / SIGNAL_FILE, today())
    record_stage('signal', ok, 'ok' if ok else f'exit {rc}')
    if not ok:
        say(f'FAILED spread signal (exit {rc})')
        notify('Gas spread signal failed', 'see the dashboard output / logs')
        return False
    ok_pub = publish(allow_stale=allow_stale, push=push)
    record_stage('publish', ok_pub, 'clean' if ok_pub else 'incomplete - see blocked')
    return ok_pub


def stage_backfill(asof=None, push=True, allow_stale=False) -> bool:
    """Recompute a past day's signal from the true 09:00-09:30 vwap.

    Trayport embargoes intraday data for 24h, so the live signal has to use
    screen prices; by the next morning the real window is available and this
    records what the signal should have been, in a separate file.
    """
    day = pd.Timestamp(asof) if asof else today() - pd.Timedelta(days=1)
    path = DAM1 / 'outputs' / BACKFILL_FILE
    if covers(path, day):
        say(f'-- skip backfill: {day:%Y-%m-%d} already recorded')
        record_stage('backfill', True, f'{day:%Y-%m-%d} already recorded')
        return True
    say(f'\n== backfill signal for {day:%Y-%m-%d} ==')
    rc = run_script(DAM1, '3-spread_forecast.py', ['--asof', f'{day:%Y-%m-%d}'])
    ok = rc == 0 and covers(path, day)
    record_stage('backfill', ok, 'ok' if ok else f'exit {rc}')
    if not ok:
        say(f'backfill did not complete (exit {rc}) - not fatal')
        return False
    publish(allow_stale=allow_stale, push=push)
    return True


def stage_check_signal() -> bool:
    """Reminder that the one manual input of the day is still outstanding."""
    if covers(DAM1 / 'outputs' / SIGNAL_FILE, today()):
        say('signal for today is in')
        return True
    notify('Gas spread signal outstanding',
           'No DA-M1 signal for today - open the dashboard and enter the 09:00-09:30 prices')
    return False


# -------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=['morning', 'signal', 'backfill', 'publish', 'check-signal'])
    ap.add_argument('--da', help="today's 09:00-09:30 DA vwap (signal stage)")
    ap.add_argument('--m1', help="today's 09:00-09:30 M1 vwap (signal stage)")
    ap.add_argument('--asof', help='day to backfill (default: yesterday)')
    ap.add_argument('--force', action='store_true', help='rerun steps even if outputs are fresh')
    ap.add_argument('--no-push', action='store_true', help='publish to data\\ but do not git push')
    ap.add_argument('--allow-stale', action='store_true',
                    help='publish files that fail their freshness contract (escape hatch)')
    args = ap.parse_args()

    for name, path in (('daily_storage_forecast', SND), ('quant_strats/DA_M1', DAM1)):
        if not path.exists():
            sys.exit(f'ERROR: {name} not found at {path} - set GAS_GITHUB_ROOT')

    log_path = open_log(args.stage)
    push = not args.no_push
    if args.stage == 'morning':
        ok = stage_morning(args.force, push, args.allow_stale)
    elif args.stage == 'signal':
        ok = stage_signal(args.da, args.m1, push, args.allow_stale)
    elif args.stage == 'backfill':
        ok = stage_backfill(args.asof, push, args.allow_stale)
    elif args.stage == 'publish':
        ok = publish(args.allow_stale, push)
        record_stage('publish', ok, 'clean' if ok else 'incomplete - see blocked')
    else:
        ok = stage_check_signal()

    say(f"\n=== {args.stage} {'OK' if ok else 'FAILED'} | {datetime.now():%H:%M:%S} ===")
    say(f'log -> {log_path}')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
