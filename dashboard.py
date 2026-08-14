"""
Gas Short-Term Outlook & Signals dashboard (DE / NL / UK).

Self-contained deploy version: reads everything from the repo-local data/
folder (populated by run_day.py from the two pipelines). Suitable for
Streamlit Community Cloud or any host with just this repo checked out.

On the host that has the pipelines checked out beside this repo, the page also
drives them: the 09:00-09:30 prices are typed in here (Trayport embargoes
intraday data for 24h, so they cannot be fetched) and run_day.py runs the
signal and publishes. On a cloud host those controls are hidden and the page
is read-only.

Run:
    streamlit run dashboard.py
"""
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))       # import works whatever cwd the host launches from
import signal_model                 # noqa: E402

DATA = HERE / 'data'

# pipelines reachable = we are on the host that can run them
GITHUB = Path(os.environ.get('GAS_GITHUB_ROOT') or HERE.parent)
LOCAL = (GITHUB / 'quant_strats' / 'DA_M1').exists()

COUNTRIES = {'DE': 'snd_de.csv', 'NL': 'snd_nl.csv', 'UK': 'snd_uk.csv'}
DEMAND_COMPONENTS = ['GFP', 'LDZ', 'Industry']          # kept if present per country
SUPPLY_COMPONENTS = ['Regas', 'Production', 'Pipeline Imports']

DEMAND_COLORS = {'GFP': '#d62728', 'LDZ': '#ff7f0e', 'Industry': '#e377c2'}
SUPPLY_COLORS = {'Regas': '#1f77b4', 'Production': '#2ca02c', 'Pipeline Imports': '#17becf'}
HILITE = 'rgba(255, 200, 0, 0.18)'      # tomorrow band / column


def today_ts() -> pd.Timestamp:
    return pd.Timestamp(datetime.today().date())


HISTORY_DAYS = 5        # past days shown, up to and including today
FORECAST_DAYS = 5       # days shown beyond today, i.e. tomorrow + 4


@st.cache_data(ttl=600)
def load_csv(fname: str) -> pd.DataFrame:
    """Load a published CSV, clipped to the common window.

    The pipelines emit different spans (the S&D tables run further back than
    the flow model, which forecasts further forward), so every panel is clipped
    to the same dates - otherwise the tables sit side by side with different
    histories and horizons.
    """
    df = pd.read_csv(DATA / fname, parse_dates=['date']).set_index('date').round(1)
    lo = today_ts() - pd.Timedelta(days=HISTORY_DAYS)
    hi = today_ts() + pd.Timedelta(days=FORECAST_DAYS)
    return df[(df.index >= lo) & (df.index <= hi)]


@st.cache_data(ttl=120)
def load_latest_signal() -> pd.Series:
    """Newest spread signal: latest trade date, latest issued run for that date."""
    log = pd.read_csv(DATA / 'spread_signal_log.csv', parse_dates=['date'])
    log = log[log['date'] == log['date'].max()]
    return log.sort_values('issued').iloc[-1]


@st.cache_data(ttl=60)
def load_status() -> dict:
    """Per-stage / per-file record written by run_day.py."""
    try:
        return json.loads((DATA / 'status.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def data_age_hours(status: dict) -> float:
    """Hours since the last clean publish (status.json, then the legacy stamp,
    then file mtime -- which on a cloud host is the deploy time)."""
    for ts_text in (status.get('updated'), _read_stamp()):
        if ts_text:
            try:
                return (pd.Timestamp(datetime.now()) - pd.Timestamp(ts_text)).total_seconds() / 3600
            except Exception:
                pass
    ts = pd.Timestamp(datetime.fromtimestamp((DATA / 'snd_de.csv').stat().st_mtime))
    return (pd.Timestamp(datetime.now()) - ts).total_seconds() / 3600


def _read_stamp():
    try:
        return (DATA / '_updated.txt').read_text().strip()
    except Exception:
        return None


def run_stage(stage_args: list, message: str) -> None:
    """Run run_day.py and stash the result for display after the rerun."""
    with st.spinner(message):
        done = subprocess.run([sys.executable, str(HERE / 'run_day.py'), *stage_args],
                              cwd=str(HERE), capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    st.session_state['run_output'] = (done.returncode,
                                      (done.stdout or '') + (done.stderr or ''))
    st.cache_data.clear()


def mark_tomorrow(fig: go.Figure, index: pd.DatetimeIndex) -> None:
    """Shaded band + label on tomorrow (the DA delivery day), if in range."""
    tmr = today_ts() + pd.Timedelta(days=1)
    if index.min() <= tmr <= index.max():
        fig.add_vrect(x0=tmr - pd.Timedelta(hours=12), x1=tmr + pd.Timedelta(hours=12),
                      fillcolor=HILITE, line_width=0,
                      annotation_text='tomorrow', annotation_position='top left')


def snd_figure(df: pd.DataFrame, country: str) -> go.Figure:
    """Stacked supply (positive) vs demand (negative) bars + balance line."""
    fig = go.Figure()
    for col in SUPPLY_COMPONENTS:
        if col in df.columns:
            fig.add_bar(x=df.index, y=df[col], name=col,
                        marker_color=SUPPLY_COLORS.get(col), opacity=0.85)
    for col in DEMAND_COMPONENTS:
        if col in df.columns:
            fig.add_bar(x=df.index, y=-df[col], name=col,
                        marker_color=DEMAND_COLORS.get(col), opacity=0.85)
    fig.add_scatter(x=df.index, y=df['Balance'], name='Balance (net injection)',
                    mode='lines+markers', line=dict(color='black', width=3))
    fig.add_hline(y=0, line_width=1, line_color='grey')
    mark_tomorrow(fig, df.index)
    fig.update_layout(
        barmode='relative',
        title=f'{country} — supply (up) vs demand (down), mcm/d',
        yaxis_title='mcm/d',
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        height=460,
        margin=dict(t=90),
    )
    return fig


def snd_table(df: pd.DataFrame):
    """Transposed table (components as rows, dates as columns), tomorrow highlighted."""
    disp = df.T
    labels = [d.strftime('%a %d %b') for d in df.index]
    disp.columns = labels
    tmr = today_ts() + pd.Timedelta(days=1)
    styler = disp.style.format('{:.1f}')
    if tmr in df.index:
        tmr_label = tmr.strftime('%a %d %b')
        styler = styler.set_properties(subset=[tmr_label],
                                       **{'background-color': '#ffe9a8',
                                          'font-weight': 'bold'})
    return styler


def balance_figure(df: pd.DataFrame, title: str, yrange=None) -> go.Figure:
    fig = go.Figure()
    for ctry, color in [('DE', '#1f77b4'), ('NL', '#ff7f0e'), ('UK', '#2ca02c')]:
        if ctry in df.columns:
            fig.add_scatter(x=df.index, y=df[ctry], name=ctry,
                            mode='lines+markers', line=dict(color=color, width=2.5))
    fig.add_hline(y=0, line_width=1, line_color='grey')
    mark_tomorrow(fig, df.index)
    fig.update_layout(title=title, height=320, yaxis_title='net injection (mcm/d)',
                      legend=dict(orientation='h', yanchor='bottom', y=1.02),
                      margin=dict(t=60, b=20))
    if yrange is not None:
        fig.update_yaxes(range=yrange, dtick=10, tick0=0)   # 10 mcm/d per gridline
    return fig


st.set_page_config(page_title='Gas Short-Term Outlook & Signals', page_icon=':bar_chart:', layout='wide')
st.title('Gas Short-Term Outlook & Signals — DE / NL / UK')

status = load_status()
age = data_age_hours(status)
blocked = status.get('blocked') or []
stamp = f'data published {age:.1f}h ago'

if blocked:
    # publish held these back rather than passing stale numbers off as fresh
    st.error(f"{stamp} — {len(blocked)} file(s) held back as stale, "
             f"showing the last good data: {'; '.join(blocked)}")
elif age > 30:
    st.warning(f'{stamp} — run the morning update + publish')
else:
    st.caption(stamp)

if status.get('stages'):
    with st.expander('pipeline status', expanded=bool(blocked)):
        st.dataframe(pd.DataFrame([
            {'stage': k, 'status': v.get('status'), 'finished': v.get('finished'),
             'detail': v.get('detail')}
            for k, v in status['stages'].items()
        ]), hide_index=True, use_container_width=True)
        if status.get('files'):
            st.dataframe(pd.DataFrame([
                {'file': k, 'published': v.get('published'),
                 'data through': v.get('data_through'), 'built': v.get('built'),
                 'note': v.get('reason', '')}
                for k, v in status['files'].items()
            ]), hide_index=True, use_container_width=True)

# ── latest DA-M1 spread signal ───────────────────────────────────────────────
st.subheader('Latest DA-M1 spread signal')
sig = None
try:
    sig = load_latest_signal()
    if sig['pred'] > 0:
        tri, color, direction = '&#9650;', '#09ab3b', 'LONG spread (long DA / short M1)'
    else:
        tri, color, direction = '&#9660;', '#ff2b2b', 'SHORT spread (short DA / long M1)'
    s1, s2, s3 = st.columns(3)
    s1.metric('Issued', str(sig['issued']),
              help=f"trade day {sig['date']:%Y-%m-%d}, entry 09:00-09:30 vwap")
    s2.caption('Prediction')
    s2.markdown(f"### <span style='color:{color}'>{tri}</span> {direction}",
                unsafe_allow_html=True)
    s3.metric('Confidence', f"{sig['confidence'] * 200:.0f}%",
              delta='TRADE' if sig['ref_trade'] else 'below gate (20%) - no trade',
              delta_color='normal' if sig['ref_trade'] else 'off',
              help='share of maximum conviction: 0% = coin flip, 100% = certain; trade gate at 20%')
    if sig['date'].date() != datetime.today().date():
        st.warning(f"signal is for {sig['date']:%Y-%m-%d}, not today")
except Exception as e:
    st.warning(f'spread signal unavailable: {e}')

# ── run controls (host with the pipelines only) ──────────────────────────────
if LOCAL:
    have_today = sig is not None and sig['date'].date() == datetime.today().date()
    with st.expander("Enter the 09:00-09:30 prices / run the pipelines",
                     expanded=not have_today):
        st.caption('Trayport embargoes intraday data for 24h, so today\'s entry '
                   'prices are the one input that cannot be fetched — read them '
                   'off the screen after 09:30.')
        with st.form('signal_form'):
            f1, f2, f3 = st.columns([2, 2, 3])
            da_in = f1.text_input('DA 09:00-09:30 vwap', placeholder='60.42')
            m1_in = f2.text_input('M1 09:00-09:30 vwap', placeholder='60.66')
            f3.write('')
            submitted = f3.form_submit_button('Run signal + publish', type='primary')
        if submitted:
            try:
                da_v = float(da_in.strip().replace(',', '.'))
                m1_v = float(m1_in.strip().replace(',', '.'))
            except ValueError:
                st.error('enter both prices as numbers')
            else:
                run_stage(['signal', '--da', str(da_v), '--m1', str(m1_v)],
                          'running the spread signal + publishing...')
                st.rerun()

        b1, b2, _ = st.columns([2, 2, 3])
        if b1.button('Run morning update', help='S&D + flow forecast, then publish — '
                                                'takes ~20 min, keep this tab open'):
            run_stage(['morning'], 'running the morning update (~20 min)...')
            st.rerun()
        if b2.button('Publish only', help='re-copy validated outputs into data\\ and push'):
            run_stage(['publish'], 'publishing...')
            st.rerun()

        if 'run_output' in st.session_state:
            code, output = st.session_state['run_output']
            (st.success if code == 0 else st.error)(f'last run finished with exit {code}')
            st.code(output[-6000:] or '(no output)')

# ── hosted: price the entry without the pipelines ────────────────────────────
elif signal_model.available(DATA):
    have_today = sig is not None and sig['date'].date() == datetime.today().date()
    with st.expander('Enter the 09:00-09:30 prices', expanded=not have_today):
        st.caption('This page cannot reach the pipelines, so it applies the '
                   'published model to the prices you enter. The result is shown '
                   'here only — the recorded signal is the one the desk machine '
                   'writes to the log.')
        with st.form('hosted_signal_form'):
            g1, g2, g3 = st.columns([2, 2, 3])
            da_in = g1.text_input('DA 09:00-09:30 vwap', placeholder='60.42')
            m1_in = g2.text_input('M1 09:00-09:30 vwap', placeholder='60.66')
            g3.write('')
            priced = g3.form_submit_button('Price this entry', type='primary')

        if priced:
            try:
                out = signal_model.evaluate(DATA,
                                            float(da_in.strip().replace(',', '.')),
                                            float(m1_in.strip().replace(',', '.')))
            except ValueError as exc:
                st.error(f'cannot price this entry: {exc}')
            else:
                spec = out['spec']
                arrow = '&#9650;' if out['pred'] > 0 else '&#9660;'
                colour = '#09ab3b' if out['pred'] > 0 else '#ff2b2b'
                side = ('LONG spread (long DA / short M1)' if out['pred'] > 0
                        else 'SHORT spread (short DA / long M1)')
                st.markdown(f"### <span style='color:{colour}'>{arrow}</span> {side}",
                            unsafe_allow_html=True)
                h1, h2, h3 = st.columns(3)
                h1.metric('Confidence', f"{out['confidence'] * 200:.0f}%",
                          delta='TRADE' if out['ref_trade'] else
                                f"below gate ({spec['CONF_REF'] * 200:.0f}%) - no trade",
                          delta_color='normal' if out['ref_trade'] else 'off')
                h2.metric('p_up', f"{out['p_up']:.3f}")
                h3.metric('PILOT gate', 'TRADE' if out['pilot_trade'] else 'no trade',
                          help=f"needs confidence > {spec['CONF_PLT'] * 200:.0f}% "
                               f"and vol21 > {spec['VOL_FLOOR']:.3f}")
                st.caption(
                    f"open_spread {out['open_spread']:+.3f} · stor_D1 {out['stor_D1']:+.2f} · "
                    f"gap_vol {out['gap_vol']:+.3f} · gap_morning {out['gap_morning']:+.3f} · "
                    f"vol21 {out['vol21']:.3f} · last close {out['last_close_day']:%Y-%m-%d}")

                stale = (pd.Timestamp(datetime.today().date()) - out['last_close_day']).days
                if stale > 4:
                    st.warning(f"the newest published close is {stale} days old — "
                               f"gap_vol is computed from stale history")

        # end-to-end check that this page still agrees with the pipeline
        check = signal_model.verify_against_log(DATA)
        if check and not check['ok']:
            st.error(f"this calculator disagrees with the pipeline — do not trust "
                     f"it until the published model is refreshed ({check['detail']})")
        elif check:
            st.caption(f"self-check: {check['detail']}")
            if check['moved']:
                st.caption('inputs have been refreshed since that signal was '
                           'issued, so a re-price now differs: '
                           + '; '.join(check['moved']))

# ── overview: balance per country, S&D pipeline vs DA_M1 flow model ─────────
st.subheader('Storage balance by country (mcm/d)')

bal = load_csv('country_balance.csv')
try:
    flow = load_csv('storage_flow_forecast.csv')[['DE', 'NL', 'UK']]
except Exception:
    flow = None

# common y-scale for both panels: pos/neg extremes across both datasets,
# snapped outward to full 10 mcm/d steps (axis ticks every 10)
frames = [bal[['DE', 'NL', 'UK']]] + ([flow] if flow is not None else [])
lo = min(f.min().min() for f in frames)
hi = max(f.max().max() for f in frames)
yrange = [min(math.floor(lo / 10) * 10, 0), max(math.ceil(hi / 10) * 10, 0)]

left, right = st.columns(2)
with left:
    st.plotly_chart(balance_figure(bal, 'SnD balance forecast', yrange), use_container_width=True)
    st.dataframe(snd_table(bal), use_container_width=True)
with right:
    if flow is not None:
        st.plotly_chart(balance_figure(flow, 'Model forecast', yrange), use_container_width=True)
        st.dataframe(snd_table(flow), use_container_width=True)
    else:
        st.warning('model forecast unavailable')

# ── per-country sections (all visible, no tabs) ──────────────────────────────
for country, fname in COUNTRIES.items():
    st.divider()
    st.header(country)
    df = load_csv(fname)

    # headline = today's forecast row (fallback: nearest date in the file)
    day = today_ts() if today_ts() in df.index else df.index[abs(df.index - today_ts()).argmin()]
    row, prev = df.loc[day], df.shift(1).loc[day]

    c1, c2, c3 = st.columns(3)
    c1.metric(f'Demand  ({day:%d %b})', f"{row['Demand']:.0f} mcm/d",
              delta=f"{row['Demand'] - prev['Demand']:+.0f} vs prev day")
    c2.metric('Supply', f"{row['Supply']:.0f} mcm/d",
              delta=f"{row['Supply'] - prev['Supply']:+.0f}")
    c3.metric('Balance', f"{row['Balance']:+.0f} mcm/d",
              delta=f"{row['Balance'] - prev['Balance']:+.0f}",
              help='Supply - Demand = implied net storage injection')

    st.plotly_chart(snd_figure(df, country), use_container_width=True)
    st.dataframe(snd_table(df), use_container_width=True)
