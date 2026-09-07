"""
Morning-window prices for the DA-M1 signal: Day Ahead + front month,
09:00-10:00 Amsterdam, from the desk's minute snapshot files.

    python fetch_vwap.py                       today, merged into data\\am_window_prices.csv
    python fetch_vwap.py --days 30             backfill
    python fetch_vwap.py --start 09:00 --end 09:30 --no-save     signal window, print only

What the snapshots can and cannot give
    Each minute file carries bid/ask QUOTES only -- no trades, no volume (the
    only Type values are 'bid' and 'ask'). A volume-weighted price is therefore
    not computable from this source. What is computed here is the plain mean
    of the one-minute mid quotes across the window, i.e. a time-weighted mid.
    The columns are still named da_vwap / m1_vwap because that is what the
    signal consumes them as. Each run prints `bars` (minutes with a two-sided
    quote, max 60), the mean bid/ask spread and a crossed-quote count, so a
    thin or wide morning is visible on the console; the CSV holds only
    date, da_vwap, m1_vwap.

Where each leg is quoted (checked on the 2026-09-07 files, 60/60 minutes)
    DA  -> instrument 'TTF Hi Cal 51.6 EEX',       Item1 'DA'
           The ICE ENDEX row has no DA outright, and the OTC 'TTF Hi Cal 51.6'
           row is bid-only.
    M1  -> instrument 'TTF Hi Cal 51.6 ICE ENDEX', Item1 'Oct-26' style label
           The label rolls monthly, so it is resolved per day from the file
           itself: the earliest quoted 'Mon-YY' contract delivering after the
           day's calendar month (Sep-26 -> Oct-26). That matches the contract
           column in DA_M1\\inputs\\M1.csv.

Files and time
    Folder names are UTC dates and so are the filename stamps (verified:
    ...-20260821-000000.csv sits in folder 2026-08-21 and its in-file
    TimeStamp reads 02:00 local). The window is defined in Europe/Amsterdam
    and converted to UTC before choosing files, so the 09:00 local start stays
    correct on both sides of a DST switch.

This runs on the desk machine only (it needs the G: drive); the hosted
dashboard just reads the CSV it writes into data\\.
"""
import argparse
import glob
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = os.environ.get('GAS_SNAPSHOT_ROOT') or (
    r'G:\4. Asset & Portfoliomanagement\5. H&O\15. Live Market View'
    r'\snapshots\natural_gas')
PAT = re.compile(r'snapshot-natural_gas-(\d{8})-(\d{2})(\d{2})(\d{2})\.csv$', re.I)
WORKERS = 16

TZ = 'Europe/Amsterdam'
DA_INSTRUMENT, DA_ITEM = 'TTF Hi Cal 51.6 EEX', 'DA'
M1_INSTRUMENT = 'TTF Hi Cal 51.6 ICE ENDEX'
MONTH_LABEL = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(\d{2})$')
WINDOW_START, WINDOW_END = '09:00', '10:00'
OUT_FILE = Path(__file__).resolve().parent / 'data' / 'am_window_prices.csv'
# the CSV carries just the two prices; bars / spread / crossed counts are
# printed per run as diagnostics but not stored
OUT_COLUMNS = ['date', 'da_vwap', 'm1_vwap']


# ------------------------------------------------------------ file access ----

def make_key(instrument, item1):
    """Byte prefix identifying the OUTRIGHT row.

    Columns are TimeStamp;Instrument;Item1;StartDate1;EndDate1;Item2;...
    The six empty fields after Item1 exclude the spread rows, which carry Item2.

    The LEADING semicolon is essential. Instrument is the second field, and
    without that anchor this key is also a substring of the spread rows --
    ';THE ICE ENDEX/TTF Hi Cal 51.6 ICE ENDEX;Oct-26;;;;;;' contains
    'TTF Hi Cal 51.6 ICE ENDEX;Oct-26;;;;;;'. That silently interleaves the
    THE/TTF spread into the outright series and shows up as negative spreads.
    """
    return f';{instrument};{item1};;;;;;'.encode()


def scan_quotes(path, keys):
    """bid/ask for several outright rows from one snapshot in a single pass.

    `keys` maps a name ('da', 'm1') to the byte prefix from make_key(). Returns
    {name: {'bid': x, 'ask': y}} with only the sides actually present.

    pandas.read_csv costs ~10 ms on these files; scanning bytes and stopping
    once every key has both sides costs well under 1 ms threaded. We only
    want four numbers, so the parser is pure overhead.
    """
    out = {name: {} for name in keys}
    want = 2 * len(keys)
    got = 0
    try:
        with open(path, 'rb') as f:
            for ln in f:
                for name, key in keys.items():
                    if key in ln:
                        p = ln.rstrip().split(b';')
                        out[name][p[8].decode()] = float(p[9])
                        got += 1
                        break
                if got >= want:
                    break
    except (OSError, ValueError, IndexError):
        return None
    return out


def front_month_label(path, day, instrument=M1_INSTRUMENT):
    """The front-month Item1 label quoted in `path` for calendar day `day`.

    Earliest 'Mon-YY' outright of `instrument` whose delivery month is after
    the day's month. Reads the file with pandas once (~10 ms) -- this runs
    once per day, not per minute. None when nothing monthly is quoted
    (weekend: ICE ENDEX carries no quotes).
    """
    df = pd.read_csv(path, sep=';', dtype=str, keep_default_na=False)
    rows = df[(df['Instrument'] == instrument) & (df['Item2'] == '')]
    month0 = pd.Timestamp(day).to_period('M')
    best = None
    for label in rows['Item1'].unique():
        m = MONTH_LABEL.match(label)
        if not m:
            continue
        period = pd.Period(f'{m[1]} 20{m[2]}', freq='M')
        if period > month0 and (best is None or period < best[0]):
            best = (period, label)
    return None if best is None else best[1]


def _window_files(root, day, start, end):
    """Snapshot files whose UTC stamp falls in [start, end) of local `day`.

    Returns (t_start, t_end, [(utc_stamp, path), ...]) sorted by time. Only
    the day folder(s) overlapping the window are touched.
    """
    t0 = pd.Timestamp(f'{pd.Timestamp(day):%Y-%m-%d} {start}', tz=TZ).tz_convert('UTC')
    t1 = pd.Timestamp(f'{pd.Timestamp(day):%Y-%m-%d} {end}', tz=TZ).tz_convert('UTC')
    hours = pd.date_range(t0.floor('h'), (t1 - pd.Timedelta(seconds=1)).floor('h'), freq='h')
    want = {(h.strftime('%Y%m%d'), h.strftime('%H')) for h in hours}

    files = []
    for dn in sorted({d for d, _ in want}):
        folder = os.path.join(root, f'{dn[:4]}-{dn[4:6]}-{dn[6:]}')
        if not os.path.isdir(folder):
            continue
        for p in glob.glob(os.path.join(folder, 'snapshot-natural_gas-*.csv')):
            m = PAT.search(os.path.basename(p))
            if not m or (m[1], m[2]) not in want:
                continue
            ts = pd.Timestamp(f'{m[1][:4]}-{m[1][4:6]}-{m[1][6:]} {m[2]}:{m[3]}:{m[4]}', tz='UTC')
            if t0 <= ts < t1:
                files.append((ts, p))
    files.sort()
    return t0, t1, files


# --------------------------------------------------------------- pricing ----

def _leg_stats(quotes):
    """Mean mid, first/last mid, mean spread and bar count from a list of
    per-minute {'bid','ask'} dicts. Returns NaNs when no minute was two-sided.

    A minute counts only when BOTH sides are present: a one-sided quote has
    no mid, and inventing one from the single side would bias the average.

    Crossed minutes (bid > ask) are dropped too and counted in `crossed`.
    The EEX DA row does show the odd stale side (2026-09-03 09:27 local:
    bid 73.20 / ask 73.15), and one such minute must not sink the day. A key
    that matches a spread row instead of the outright makes EVERY minute
    negative, so that case is still caught: raise when most bars are crossed.
    """
    mids, spreads, crossed = [], [], 0
    for q in quotes:
        if not (q and 'bid' in q and 'ask' in q):
            continue
        if q['ask'] < q['bid']:
            crossed += 1
            continue
        mids.append((q['bid'] + q['ask']) / 2.0)
        spreads.append(q['ask'] - q['bid'])
    if crossed > len(mids):
        raise ValueError(f'{crossed} of {crossed + len(mids)} minutes have bid > ask -- '
                         f'the row key is matching a spread row, not the outright')
    if not mids:
        return dict(px=np.nan, first=np.nan, last=np.nan, spread=np.nan, bars=0, crossed=crossed)
    return dict(px=float(np.mean(mids)), first=mids[0], last=mids[-1],
                spread=float(np.mean(spreads)), bars=len(mids), crossed=crossed)


def window_prices(day=None, start=WINDOW_START, end=WINDOW_END, root=ROOT,
                  workers=WORKERS, now=None, verbose=True):
    """DA and front-month mid-quote averages over [start, end) local time.

    One dict per call with the full diagnostics (da_px, da_bars, da_spread,
    da_crossed, m1_contract, m1_px, ..., n_files, partial); window_history()
    keeps only the two prices for the CSV. `partial` is True when the window
    has not finished yet at `now`, so a 09:20 run is visibly incomplete.
    A day with no two-sided quotes (weekend, holiday, drive outage) still
    returns a row, with NaN prices and bars=0, so history stays gap-free.
    """
    now = (pd.Timestamp.now(tz='UTC') if now is None
           else pd.Timestamp(now).tz_convert('UTC'))
    day = pd.Timestamp(now.tz_convert(TZ).date() if day is None else day)
    _, t1, files = _window_files(root, day, start, end)

    row = dict(date=f'{day:%Y-%m-%d}', window=f'{start}-{end}', n_files=len(files),
               partial=bool(now < t1), m1_contract=None)
    for leg in ('da', 'm1'):
        row.update({f'{leg}_px': np.nan, f'{leg}_first': np.nan, f'{leg}_last': np.nan,
                    f'{leg}_spread': np.nan, f'{leg}_bars': 0, f'{leg}_crossed': 0})
    if not files:
        if verbose:
            print(f'{day:%Y-%m-%d}: no snapshot files in {start}-{end} {TZ}')
        return row

    m1_label = front_month_label(files[0][1], day)
    keys = {'da': make_key(DA_INSTRUMENT, DA_ITEM)}
    if m1_label:
        keys['m1'] = make_key(M1_INSTRUMENT, m1_label)
    row['m1_contract'] = m1_label

    tt = time.time()
    with ThreadPoolExecutor(workers) as pool:
        scans = list(pool.map(lambda f: scan_quotes(f[1], keys), files))

    for leg in keys:
        stats = _leg_stats([s[leg] if s else None for s in scans])
        row.update({f'{leg}_{k}': v for k, v in stats.items()})

    if verbose:
        flag = '  (window still open)' if row['partial'] else ''
        print(f"{day:%Y-%m-%d} {start}-{end}: DA {row['da_px']:.3f} ({row['da_bars']} bars, "
              f"spread {row['da_spread']:.3f})  M1 {m1_label} {row['m1_px']:.3f} "
              f"({row['m1_bars']} bars, spread {row['m1_spread']:.3f})  "
              f"[{len(files)} files, {time.time() - tt:.1f}s]{flag}")
    return row


def window_history(days=1, end_day=None, **kw):
    """window_prices() for the last `days` calendar days ending at `end_day`
    (default today), oldest first, reduced to OUT_COLUMNS: one row per date
    with the DA and front-month window prices."""
    end_day = pd.Timestamp(end_day) if end_day else pd.Timestamp.now(tz=TZ).normalize().tz_localize(None)
    rows = [window_prices(d, **kw) for d in pd.date_range(end=end_day, periods=days, freq='D')]
    return pd.DataFrame([dict(date=r['date'], da_vwap=r['da_px'], m1_vwap=r['m1_px'])
                         for r in rows], columns=OUT_COLUMNS)


def save_history(df, path=OUT_FILE):
    """Merge into the CSV keyed on date; new rows win, so a partial morning
    run is overwritten by the complete one later. Returns the merged frame."""
    path = Path(path)
    if path.exists():
        old = pd.read_csv(path, dtype={'date': str})
        df = pd.concat([old, df], ignore_index=True)
    df = (df.drop_duplicates(subset=['date'], keep='last')
            .sort_values('date').reset_index(drop=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, float_format='%.4f')
    return df


# ------------------------------------------------------------------ main ----

def main():
    ap = argparse.ArgumentParser(description='DA + front-month mid-quote average over the '
                                             'morning window, from the local minute snapshots')
    ap.add_argument('--days', type=int, default=1, help='calendar days back, incl. today (default 1)')
    ap.add_argument('--asof', help='last day to compute (default today)')
    ap.add_argument('--start', default=WINDOW_START, help=f'window start, {TZ} (default {WINDOW_START})')
    ap.add_argument('--end', default=WINDOW_END, help=f'window end, {TZ} (default {WINDOW_END})')
    ap.add_argument('--out', default=str(OUT_FILE), help=f'CSV to merge into (default {OUT_FILE})')
    ap.add_argument('--no-save', action='store_true', help='print only, do not touch the CSV')
    args = ap.parse_args()

    df = window_history(args.days, args.asof, start=args.start, end=args.end)
    if not args.no_save:
        save_history(df, args.out)
        print(f'-> {args.out}')
    return df


if __name__ == '__main__':
    main()
