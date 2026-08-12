"""
Gas Short-Term Outlook & Signals dashboard (DE / NL / UK).

Self-contained deploy version: reads everything from the repo-local data/
folder (populated by publish_data.ps1 / spread_signal.ps1 from the two
pipelines). Suitable for Streamlit Community Cloud or any host with just
this repo checked out.

Run:
    streamlit run dashboard.py
"""
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).resolve().parent / 'data'

COUNTRIES = {'DE': 'snd_de.csv', 'NL': 'snd_nl.csv', 'UK': 'snd_uk.csv'}
DEMAND_COMPONENTS = ['GFP', 'LDZ', 'Industry']          # kept if present per country
SUPPLY_COMPONENTS = ['Regas', 'Production', 'Pipeline Imports']

DEMAND_COLORS = {'GFP': '#d62728', 'LDZ': '#ff7f0e', 'Industry': '#e377c2'}
SUPPLY_COLORS = {'Regas': '#1f77b4', 'Production': '#2ca02c', 'Pipeline Imports': '#17becf'}
HILITE = 'rgba(255, 200, 0, 0.18)'      # tomorrow band / column


def today_ts() -> pd.Timestamp:
    return pd.Timestamp(datetime.today().date())


@st.cache_data(ttl=600)
def load_csv(fname: str) -> pd.DataFrame:
    return pd.read_csv(DATA / fname, parse_dates=['date']).set_index('date').round(1)


@st.cache_data(ttl=120)
def load_latest_signal() -> pd.Series:
    """Newest spread signal: latest trade date, latest issued run for that date."""
    log = pd.read_csv(DATA / 'spread_signal_log.csv', parse_dates=['date'])
    log = log[log['date'] == log['date'].max()]
    return log.sort_values('issued').iloc[-1]


def data_age_hours() -> float:
    """Hours since the data was published (stamp written by publish_data.ps1;
    falls back to file mtime, which on a cloud host = deploy time)."""
    stamp = DATA / '_updated.txt'
    try:
        ts = pd.Timestamp(stamp.read_text().strip())
    except Exception:
        ts = pd.Timestamp(datetime.fromtimestamp((DATA / 'snd_de.csv').stat().st_mtime))
    return (pd.Timestamp(datetime.now()) - ts).total_seconds() / 3600


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

age = data_age_hours()
stamp = f'data published {age:.1f}h ago'
if age > 30:
    st.warning(f'{stamp} — run the morning update + publish')
else:
    st.caption(stamp)

# ── latest DA-M1 spread signal ───────────────────────────────────────────────
st.subheader('Latest DA-M1 spread signal')
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
    s3.metric('Confidence', f"{sig['confidence']:.2f}",
              delta='TRADE' if sig['ref_trade'] else 'below gate (0.10) - no trade',
              delta_color='normal' if sig['ref_trade'] else 'off')
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
