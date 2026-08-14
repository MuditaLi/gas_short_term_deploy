"""
The frozen DA-M1 spread model, evaluated from the published data/ folder.

3-spread_forecast.py on the desk machine stays the authority: it is what runs
the Trayport refresh, writes the signal log and produces the tradeable record.
This module applies the same frozen spec to the same published inputs so the
hosted dashboard can price the 09:00-09:30 entry from anywhere, with no access
to the desk machine and no credentials.

Nothing here is fitted, and the spec constants are deliberately NOT copied:
they are read from spread_spec.json, which run_day.py extracts from
3-spread_forecast.py itself at publish time. The feature definitions are the
one thing that does live in two places, so verify_against_log() re-derives the
last logged signal from published data and reports any disagreement - that is
what catches drift after a retrain, rather than a silently wrong number.
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

REQUIRED = ('price_history.csv', 'spread_model_params.csv', 'spread_spec.json',
            'storage_flow_forecast.csv')


def available(data_dir) -> bool:
    return all((data_dir / f).exists() for f in REQUIRED)


def load_spec(data_dir) -> dict:
    return json.loads((data_dir / 'spread_spec.json').read_text(encoding='utf-8'))


def load_params(data_dir) -> pd.Series:
    return pd.read_csv(data_dir / 'spread_model_params.csv').set_index('feature')['coef']


def close_spread(data_dir) -> pd.Series:
    """Daily 17:00-17:30 vwap spread, the series the model was trained on."""
    px = pd.read_csv(data_dir / 'price_history.csv', parse_dates=['date']).set_index('date')
    return (px['da_vwap'] - px['m1_vwap']).dropna()


def storage_delta(data_dir, trade_day) -> float:
    """stor_D1 = DE net injection forecast for tomorrow minus today."""
    sf = pd.read_csv(data_dir / 'storage_flow_forecast.csv',
                     parse_dates=['date']).set_index('date')
    next_day = trade_day + pd.Timedelta(days=1)
    for day in (trade_day, next_day):
        if day not in sf.index or pd.isna(sf.loc[day, 'DE']):
            raise ValueError(f'no DE storage forecast for {day:%Y-%m-%d}')
    return float(sf.loc[next_day, 'DE'] - sf.loc[trade_day, 'DE'])


def evaluate(data_dir, da_price: float, m1_price: float, trade_day=None) -> dict:
    """Signal for an entry at `da_price`/`m1_price`, features as in training."""
    spec, beta = load_spec(data_dir), load_params(data_dir)
    trade_day = pd.Timestamp(trade_day or datetime.today().date()).normalize()

    hist = close_spread(data_dir)
    c = hist[hist.index < trade_day]                  # history only, no same-day data
    if len(c) < spec['VOL_W'] + 2:
        raise ValueError(f"only {len(c)} days of close-spread history; "
                         f"need > {spec['VOL_W'] + 2}")

    vol21 = float(c.diff().tail(spec['VOL_W']).std())
    gap = float(c.iloc[-1] - c.tail(spec['GAP_W']).mean())
    gap_vol = gap / vol21
    open_spread = da_price - m1_price
    gap_morning = open_spread - float(c.iloc[-1])
    stor_d1 = storage_delta(data_dir, trade_day)

    z = (beta['const']
         + beta['stor_D1']     * stor_d1
         + beta['gap_vol']     * gap_vol
         + beta['gap_morning'] * gap_morning)
    p_up = float(1.0 / (1.0 + np.exp(-z)))
    conf = abs(p_up - 0.5)

    return {
        'trade_day': trade_day, 'open_spread': open_spread,
        'stor_D1': stor_d1, 'gap_vol': gap_vol, 'gap_morning': gap_morning,
        'vol21': vol21, 'p_up': p_up, 'confidence': conf,
        'pred': 1 if p_up > 0.5 else -1,
        'ref_trade': conf > spec['CONF_REF'],
        'pilot_trade': (conf > spec['CONF_PLT']) and (vol21 > spec['VOL_FLOOR']),
        'last_close_day': c.index.max(), 'spec': spec,
    }


def verify_against_log(data_dir, tol: float = 5e-4):
    """Re-derive the newest logged signal from published data.

    The log stores the prices that were entered and the resulting p_up, so
    recomputing it here is an end-to-end check that this module still agrees
    with the pipeline. Returns None when the check cannot be run (the flow
    forecast only carries the current issue, so older days are not
    reproducible), otherwise {'ok': bool, 'detail': str}.
    """
    try:
        log = pd.read_csv(data_dir / 'spread_signal_log.csv', parse_dates=['date'])
        row = log[log['date'] == log['date'].max()].sort_values('issued').iloc[-1]
        got = evaluate(data_dir, float(row['da_am']), float(row['m1_am']), row['date'])
    except Exception:
        return None

    diffs = [f"{k} {got[k]:+.4f} vs logged {float(row[k]):+.4f}"
             for k in ('stor_D1', 'gap_vol', 'gap_morning', 'p_up')
             if abs(got[k] - float(row[k])) > tol]
    if diffs:
        return {'ok': False,
                'detail': f"{row['date']:%Y-%m-%d}: " + '; '.join(diffs)}
    return {'ok': True,
            'detail': f"reproduces the {row['date']:%Y-%m-%d} signal "
                      f"(p_up {got['p_up']:.4f})"}
