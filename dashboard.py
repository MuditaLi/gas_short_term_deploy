"""
Gas Short-Term Outlook & Signals dashboard (DE / NL / UK).

Self-contained, read-only deploy version: reads everything from the repo-local
data/ folder (populated by run_day.py, which the scheduler runs). Suitable for
Streamlit Community Cloud or any host with just this repo checked out.

Per country it shows the assembled S&D table plus two pieces of context the
S&D pipeline computes behind it: the regas step's LNG shock check (Kpler
arrivals vs the recent-level anchor - alert-only, the forecast is not
adjusted) and LDZ demand under the second weather model (gfsop; the tables
use ecop), drawn as an alternative balance line.

Run:
    streamlit run dashboard.py
"""
import json
import math
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
DATA = HERE / 'data'

COUNTRIES = {'DE': 'snd_de.csv', 'NL': 'snd_nl.csv', 'UK': 'snd_uk.csv'}
DEMAND_COMPONENTS = ['GFP', 'LDZ', 'Industry']          # kept if present per country
SUPPLY_COMPONENTS = ['Regas', 'Production', 'Pipeline Imports']

DEMAND_COLORS = {'GFP': '#d62728', 'LDZ': '#ff7f0e', 'Industry': '#e377c2'}
SUPPLY_COLORS = {'Regas': '#1f77b4', 'Production': '#2ca02c', 'Pipeline Imports': '#17becf'}
HILITE = 'rgba(255, 200, 0, 0.18)'      # tomorrow band / column


def today_ts() -> pd.Timestamp:
    return pd.Timestamp(datetime.today().date())


HISTORY_DAYS = 3        # past days shown, up to and including today
FORECAST_DAYS = 6       # days shown beyond today, i.e. t+1 through t+6


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


@st.cache_data(ttl=600)
def load_lng_alerts():
    """LNG shock check per country/day from the S&D regas step, or None.

    The pipeline compares Kpler cargo arrivals (through a calibrated release
    kernel) with its recent-level regas anchor; a day whose divergence trips the
    threshold is flagged (alert=True, lng_adjust = the nudge it would have
    applied). The regas forecast itself is deliberately NOT adjusted - the flag
    marks the day as low-confidence. An empty file means the check did not run
    (Kpler unreachable) for the newest forecast.
    """
    try:
        return pd.read_csv(DATA / 'regas_lng_alerts.csv', parse_dates=['date'])
    except Exception:
        return None


@st.cache_data(ttl=600)
def load_ldz_models():
    """LDZ demand under both weather models (columns like DE_ecop, DE_gfsop), or None.

    The S&D tables use ecop; the gfsop column shows how much of the balance
    hangs on the weather model."""
    try:
        df = pd.read_csv(DATA / 'ldz_models.csv', parse_dates=['date']).set_index('date').round(1)
        lo = today_ts() - pd.Timedelta(days=HISTORY_DAYS)
        hi = today_ts() + pd.Timedelta(days=FORECAST_DAYS)
        return df[(df.index >= lo) & (df.index <= hi)]
    except Exception:
        return None


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
    then file mtime -- which on a cloud host is the deploy time).

    'updated_epoch' is preferred because it is an absolute instant: 'updated'
    is naive local time on the publishing machine, and the hosted container
    runs in UTC, so subtracting it from a local now() reported a negative age.
    """
    epoch = status.get('updated_epoch')
    if isinstance(epoch, (int, float)):
        return (time.time() - epoch) / 3600
    for ts_text in (status.get('updated'), _read_stamp()):
        if ts_text:
            try:
                return (pd.Timestamp(datetime.now()) - pd.Timestamp(ts_text)).total_seconds() / 3600
            except Exception:
                pass
    return (time.time() - (DATA / 'snd_de.csv').stat().st_mtime) / 3600


def _read_stamp():
    try:
        return (DATA / '_updated.txt').read_text().strip()
    except Exception:
        return None


def mark_tomorrow(fig: go.Figure, index: pd.DatetimeIndex) -> None:
    """Shaded band + label on tomorrow (the DA delivery day), if in range."""
    tmr = today_ts() + pd.Timedelta(days=1)
    if index.min() <= tmr <= index.max():
        fig.add_vrect(x0=tmr - pd.Timedelta(hours=12), x1=tmr + pd.Timedelta(hours=12),
                      fillcolor=HILITE, line_width=0,
                      annotation_text='tomorrow', annotation_position='top left')


def snd_figure(df: pd.DataFrame, country: str, alt_balance=None, lng_alert_days=()) -> go.Figure:
    """Stacked supply (positive) vs demand (negative) bars + balance line.

    alt_balance: the balance with LDZ from the other weather model (dashed).
    lng_alert_days: dates the regas LNG shock check flagged (marked above the bars).
    """
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
    if alt_balance is not None:
        fig.add_scatter(x=alt_balance.index, y=alt_balance, name='Balance with gfsop LDZ',
                        mode='lines', line=dict(color='#7f7f7f', width=2, dash='dash'))
    fig.add_hline(y=0, line_width=1, line_color='grey')
    mark_tomorrow(fig, df.index)
    top = df['Supply'].max()
    for day in lng_alert_days:
        if day in df.index:
            fig.add_annotation(x=day, y=top, text='LNG &#9888;', showarrow=False,
                               yshift=14, font=dict(color='#b8860b', size=12),
                               hovertext='regas: LNG shock alert (low confidence)')
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


st.set_page_config(page_title='Gas Short-Term Outlook & Signals', page_icon=':arrow_up:', layout='wide')
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
    s1, s_da, s_m1, s2, s3 = st.columns([1.3, 1, 1, 2, 1.3])
    s1.metric('Issued', str(sig['issued']),
              help=f"trade day {sig['date']:%Y-%m-%d}")
    s_da.metric('DA vwap', f"{sig['da_am']:.3f}",
                help='Day Ahead entry price: 09:00-10:00 Amsterdam mid-quote average '
                     'from the desk snapshots (fetch_vwap.py)')
    s_m1.metric('M1 vwap', f"{sig['m1_am']:.3f}",
                delta=f"spread {sig['open_spread']:+.3f}", delta_color='off',
                help='Front-month entry price, same window; delta = DA - M1 entry spread')
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
lng_alerts = load_lng_alerts()
ldz_models = load_ldz_models()
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

    # LDZ under the other weather model: the S&D tables use ecop, so the gfsop
    # column shows how much of the balance hangs on the weather model
    table_df, alt_balance = df, None
    if ldz_models is not None and {f'{country}_ecop', f'{country}_gfsop'} <= set(ldz_models.columns):
        shift = (ldz_models[f'{country}_gfsop'] - ldz_models[f'{country}_ecop']).reindex(df.index)
        alt_balance = (df['Balance'] - shift).dropna().round(1)
        table_df = df.copy()
        table_df['LDZ (gfsop)'] = ldz_models[f'{country}_gfsop'].reindex(df.index)
        table_df['Balance with gfsop LDZ'] = alt_balance
        tmr = today_ts() + pd.Timedelta(days=1)
        if tmr in shift.index and pd.notna(shift[tmr]) and abs(shift[tmr]) >= 1:
            st.caption(f"weather-model spread: gfsop puts LDZ {shift[tmr]:+.1f} mcm/d vs ecop "
                       f"tomorrow, i.e. balance {-shift[tmr]:+.1f} mcm/d")

    # LNG shock check from the regas step (alert-only: the forecast is not adjusted)
    alert_days = ()
    if lng_alerts is not None:
        chk = lng_alerts[(lng_alerts['country'] == country) & lng_alerts['date'].isin(df.index)]
        fired = chk[chk['alert']]
        if fired.empty and chk.empty:
            st.caption('LNG arrivals check did not run for this forecast (Kpler unreachable) — '
                       'regas is the recent-level model alone')
        elif fired.empty:
            st.caption(f"LNG arrivals check: no shock flagged "
                       f"(max divergence {chk['lng_divergence'].abs().max():.1f} mcm/d)")
        else:
            alert_days = tuple(fired['date'])
            days = '; '.join(f"{d:%a %d %b} ({v:+.1f} mcm/d, would-be nudge {a:+.1f})"
                             for d, v, a in zip(fired['date'], fired['lng_divergence'], fired['lng_adjust']))
            st.warning(f"LNG shock alert — cargo arrivals imply regas send-out well away from the "
                       f"recent-level anchor on {days}. The regas forecast is NOT adjusted; "
                       f"treat these days as low-confidence.")

    st.plotly_chart(snd_figure(df, country, alt_balance, alert_days), use_container_width=True)
    st.dataframe(snd_table(table_df), use_container_width=True)
