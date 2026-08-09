import streamlit as st
import duckdb
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import yfinance as yf
from dotenv import load_dotenv

# --- PAGE CONFIGURATION & GLOBALS ---
st.set_page_config(page_title="Institutional Options Radar", layout="wide", page_icon="🎯")

MARKET_HOLIDAYS = [
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
    '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25'
]

SECTOR_MAP = {
    "XLY": "Cons. Disc.", "XLF": "Financials", "XLC": "Comm. Svcs", "XTN": "Transportation",
    "XLU": "Utilities", "XLI": "Industrials", "XLK": "Technology", "XLRE": "Real Estate",
    "XLP": "Cons. Staples", "XLB": "Materials", "XLV": "Healthcare", "XLE": "Energy",
    "GLD": "Gold", "SLV": "Silver", "TLT": "Treasuries", "USO": "Oil"
}

COT_MAP = {
    "Equities": {
        "S&P 500 (E-Mini)": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "Nasdaq 100": "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
        "Russell 2000": "RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE",
        "Dow Jones": "DOW JONES",
    },
    "Metals & Energy": {
        "Gold": "GOLD - COMMODITY EXCHANGE INC.",
        "Silver": "SILVER - COMMODITY EXCHANGE INC.",
        "Copper": "COPPER-GRADE #1 - COMMODITY EXCHANGE INC.",
        "Crude Oil (WTI)": "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
    },
    "Currencies": {
        "Euro": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "Japanese Yen": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
        "British Pound": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
        "Aussie Dollar": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "Canadian Dollar": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "Swiss Franc": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE"
    }
}


# --- UI FORMATTING HELPERS ---
def get_exp_label(date_str):
    try:
        dt = pd.to_datetime(date_str)
        if dt.weekday() != 4:
            return f"{date_str} (Daily)"
        elif 15 <= dt.day <= 21:
            return f"{date_str} (Monthly)"
        else:
            return f"{date_str} (Weekly)"
    except:
        return str(date_str)


if 'saved_months' not in st.session_state: st.session_state.saved_months = {}
if 'saved_exps' not in st.session_state: st.session_state.saved_exps = {}



def render_two_step_selector(unique_id, available_exps, is_multi=True):
    if not available_exps: return [] if is_multi else None
    
    # Calculate Current Week Exps
    try:
        sel_dt = pd.to_datetime(selected_date)
        friday_dt = sel_dt + pd.Timedelta(days=(4 - sel_dt.weekday()))
        friday_str = friday_dt.strftime('%Y-%m-%d')
        cw_name = f"Current Week (End {friday_str})"
        
        week_start = sel_dt - pd.Timedelta(days=sel_dt.weekday())
        week_end = week_start + pd.Timedelta(days=4)
        cw_exps = [e for e in available_exps if pd.to_datetime(e) > sel_dt + pd.Timedelta(days=1) and week_start <= pd.to_datetime(e) <= week_end]
    except:
        cw_name = None
        cw_exps = []
        
    months = sorted(list(set([e[:7] for e in available_exps])))
    if not is_multi and cw_exps:
        months = [cw_name] + months
        
    saved_m = st.session_state.saved_months.get(unique_id)
    
    col_m, col_e = st.columns([1, 2])
    with col_m:
        if is_multi:
            saved_m = saved_m if isinstance(saved_m, list) else []
            valid_m_defaults = [m for m in saved_m if m in months]
            if not valid_m_defaults and months: valid_m_defaults = [months[0]]
            sel_m = st.multiselect("Filter by Month(s):", months, default=valid_m_defaults,
                                   format_func=lambda x: pd.to_datetime(x).strftime('%B %Y') if '-' in x else x, key=f"m_{unique_id}")
        else:
            m_index = months.index(saved_m) if saved_m in months else 0
            sel_m = st.selectbox("Filter by Month:", months, index=m_index,
                                 format_func=lambda x: pd.to_datetime(x).strftime('%B %Y') if '-' in x and not str(x).startswith("Current") else x, key=f"m_{unique_id}")
        st.session_state.saved_months[unique_id] = sel_m

    if not is_multi and sel_m == cw_name:
        # Hide the second dropdown, return special string
        special_val = "Current Week|" + "|".join(cw_exps)
        st.session_state.saved_exps[unique_id] = special_val
        return special_val
        
    filtered_exps = [e for e in available_exps if any(e.startswith(m) for m in sel_m)] if is_multi else [e for e in available_exps if e.startswith(sel_m)]

    with col_e:
        saved_e = st.session_state.saved_exps.get(unique_id)
        if is_multi:
            saved_e = saved_e if isinstance(saved_e, list) else []
            valid_defaults = [e for e in saved_e if e in filtered_exps]
            if not valid_defaults and filtered_exps: valid_defaults = [filtered_exps[0]]
            sel_e = st.multiselect("Select Expirations:", filtered_exps, default=valid_defaults, max_selections=5,
                                   format_func=get_exp_label, key=f"e_{unique_id}")
            st.session_state.saved_exps[unique_id] = sel_e
            return sel_e
        else:
            e_index = filtered_exps.index(saved_e) if saved_e in filtered_exps else 0
            if not filtered_exps: return None
            sel_e = st.selectbox("Select Expiration:", filtered_exps, index=e_index, format_func=get_exp_label,
                                 key=f"e_{unique_id}")
            st.session_state.saved_exps[unique_id] = sel_e
            return sel_e

def filter_by_exp(df, sel_exp):
    if not sel_exp: return df
    if isinstance(sel_exp, list):
        return df[df['expiration'].isin(sel_exp)]
    if str(sel_exp).startswith("Current Week"):
        dates = str(sel_exp).split("|")[1:]
        return df[df['expiration'].isin(dates)]
    return df[df['expiration'] == sel_exp]

import scipy.stats as stats
import scipy.special as spc

def bs_gamma(S, K, T, r, sigma):
    T = np.maximum(T, 1/365.0)
    sigma = np.maximum(sigma, 0.01)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    gamma = np.exp(-0.5 * d1**2) / (np.sqrt(2 * np.pi) * S * sigma * np.sqrt(T))
    return gamma

def bs_delta(S, K, T, r, sigma, is_call):
    T = np.maximum(T, 1/365.0)
    sigma = np.maximum(sigma, 0.01)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    cdf_d1 = 0.5 * (1 + spc.erf(d1 / np.sqrt(2)))
    delta = np.where(is_call, cdf_d1, cdf_d1 - 1.0)
    return delta
@st.cache_resource(ttl=3600)
def init_db_and_summary():
    load_dotenv()
    aws_key = os.getenv('AWS_ACCESS_KEY')
    aws_secret = os.getenv('AWS_SECRET_KEY')
    bucket_name = os.getenv('S3_BUCKET_NAME')

    if not aws_key or not aws_secret:
        st.error("Critical Error: AWS credentials not found. Check your .env file.")
        return None, pd.DataFrame(), ""

    con = duckdb.connect(':memory:')
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
    con.execute("SET http_keep_alive=false;")
    con.execute("SET http_timeout=300000;")
    con.execute("SET http_retries=5;")
    con.execute("SET http_retry_wait_ms=5000;")
    con.execute(f"CREATE SECRET (TYPE S3, KEY_ID '{aws_key}', SECRET '{aws_secret}', REGION 'us-east-2');")

    try:
        df_summary = con.execute(
            f"SELECT * FROM read_parquet('s3://{bucket_name}/dashboard_data/ticker_summary_gold.parquet') WHERE strftime(date, '%Y-%m-%d') NOT IN {tuple(MARKET_HOLIDAYS)} ORDER BY date ASC").df()
        return con, df_summary, bucket_name
    except Exception as e:
        st.error(f"Error connecting to S3 for summary: {e}")
        return None, pd.DataFrame(), ""


@st.cache_data(ttl=86400)
def fetch_days_to_earnings(ticker):
    if ticker.startswith('$') or ticker in ['SPY', 'QQQ', 'IWM', 'DIA', 'VXX']: return "N/A"
    try:
        t = yf.Ticker(ticker)
        today = pd.Timestamp.now().replace(tzinfo=None)
        if 'earningsTimestamp' in t.info and t.info['earningsTimestamp'] is not None:
            clean_date = pd.to_datetime(t.info['earningsTimestamp'], unit='s').replace(tzinfo=None)
            if clean_date > today: return f"{(clean_date - today).days} Days"
        return "TBD"
    except:
        return "TBD"

@st.cache_data(ttl=86400)
def fetch_restricted_earnings_dates(ticker):
    if ticker.startswith('$') or ticker in ['SPY', 'QQQ', 'IWM', 'DIA', 'VXX']: return set()
    try:
        t = yf.Ticker(ticker)
        df = t.get_earnings_dates(limit=30)
        if df is not None and not df.empty:
            dates = pd.to_datetime(df.index).tz_localize(None).normalize()
            restricted = set()
            for d in dates:
                restricted.add(d.strftime('%Y-%m-%d'))
                restricted.add((d - pd.offsets.BDay(1)).strftime('%Y-%m-%d'))
                restricted.add((d + pd.offsets.BDay(1)).strftime('%Y-%m-%d'))
            return restricted
    except:
        pass
    return set()


@st.cache_data(ttl=86400)
def fetch_company_info(ticker):
    if ticker.startswith('$') or ticker in ['SPY', 'QQQ', 'IWM', 'DIA', 'VXX']: return {"name": ticker,
                                                                                        "description": "ETF/Index.",
                                                                                        "market_cap": "N/A",
                                                                                        "pe_ratio": "N/A"}
    try:
        t = yf.Ticker(ticker)
        mc = t.info.get('marketCap', 0)
        mc_str = f"${mc / 1e12:.2f}T" if mc >= 1e12 else (f"${mc / 1e9:.2f}B" if mc >= 1e9 else f"${mc / 1e6:.2f}M")
        pe = t.info.get('trailingPE', t.info.get('forwardPE', 'N/A'))
        return {"name": t.info.get('shortName', ticker),
                "description": t.info.get('longBusinessSummary', 'No description.'), "market_cap": mc_str,
                "pe_ratio": f"{pe:.2f}" if isinstance(pe, (float, int)) else "N/A"}
    except:
        return {"name": ticker, "description": "N/A", "market_cap": "N/A", "pe_ratio": "N/A"}



def render_omni_volatility(ticker_chain_df, ts_20d_df, key_suffix=""):
    st.subheader("Omni-Volatility Dynamics (Filtered Scope)")
    c_mode, c_bar, c_exp, c_togg = st.columns([1.5, 1.2, 1, 1])
    with c_mode:
        iv_scope = st.radio("Trend Scope:", ["Front-Month (7-45 DTE)", "Specific Expiration"], horizontal=True,
                            label_visibility="collapsed", key=f"iv_scope_{key_suffix}")
    with c_bar:
        bar_mode = st.radio("Background Bars:", ["Volume (Flow)", "Open Interest (Structure)"], horizontal=True,
                            label_visibility="collapsed", key=f"bar_mode_{key_suffix}")
    with c_exp:
        selected_iv_exp = render_two_step_selector("iv_trend_"+key_suffix, sorted(ticker_chain_df['expiration'].dropna().unique()),
                                                   is_multi=False) if iv_scope == "Specific Expiration" else None
    with c_togg:
        show_10_delta = st.checkbox("Show <10Δ Wings", value=True, key=f"show_10_{key_suffix}")

    omni_data, prev_call_oi, prev_put_oi = [], None, None
    for d in ts_20d_df['date_str'].unique():
        day_df = ticker_chain_df[ticker_chain_df['date_str'] == d].copy()
        if day_df.empty or 'underlying_price' not in day_df.columns: continue
        spot = day_df['underlying_price'].iloc[0]
        if pd.isna(spot) or spot == 0: continue

        if iv_scope == "Front-Month (7-45 DTE)":
            valid_df = day_df[(day_df['dte'] >= 7) & (day_df['dte'] <= 45)].copy()
        elif selected_iv_exp:
            valid_df = day_df[day_df['expiration'] == selected_iv_exp].copy()
        else:
            continue

        if valid_df.empty: continue

        call_vol, put_vol = valid_df[valid_df['side'] == 'CALL']['volume'].sum(), valid_df[valid_df['side'] == 'PUT']['volume'].sum()
        call_oi, put_oi = valid_df[valid_df['side'] == 'CALL']['open_interest'].sum(), valid_df[valid_df['side'] == 'PUT']['open_interest'].sum()
        total_vol, total_oi = call_vol + put_vol, call_oi + put_oi

        c_pct = f"{(call_vol / total_vol * 100):.0f}%" if bar_mode == "Volume (Flow)" and total_vol > 0 else (f"{(call_oi / total_oi * 100):.0f}%" if total_oi > 0 else "")
        p_pct = f"{(put_vol / total_vol * 100):.0f}%" if bar_mode == "Volume (Flow)" and total_vol > 0 else (f"{(put_oi / total_oi * 100):.0f}%" if total_oi > 0 else "")

        c_delta_str = f"ΔOI: {(call_oi - prev_call_oi):+,.0f}" if prev_call_oi is not None and (call_oi - prev_call_oi) != 0 else ""
        p_delta_str = f"ΔOI: {(put_oi - prev_put_oi):+,.0f}" if prev_put_oi is not None and (put_oi - prev_put_oi) != 0 else ""
        prev_call_oi, prev_put_oi = call_oi, put_oi

        valid_df['strike_dist'] = (valid_df['strike'] - spot).abs()
        atm_iv = valid_df[valid_df['strike'] == valid_df.loc[valid_df['strike_dist'].idxmin(), 'strike']]['iv'].mean() if not valid_df['strike_dist'].isna().all() else np.nan

        calls, puts = valid_df[valid_df['side'] == 'CALL'], valid_df[valid_df['side'] == 'PUT']
        d25_c_iv = calls[(calls['delta'] >= 0.20) & (calls['delta'] <= 0.30)]['iv'].mean()
        d25_p_iv = puts[(puts['delta'] <= -0.20) & (puts['delta'] >= -0.30)]['iv'].mean()
        d10_c_iv = calls[(calls['delta'] > 0) & (calls['delta'] <= 0.10)]['iv'].mean()
        d10_p_iv = puts[(puts['delta'] < 0) & (puts['delta'] >= -0.10)]['iv'].mean()
        weighted_iv = np.average(valid_df['iv'], weights=valid_df['open_interest']) if valid_df['open_interest'].sum() > 0 else np.nan

        omni_data.append({
            'date_str': d, 'Call Vol': call_vol, 'Put Vol': put_vol, 'Call OI': call_oi, 'Put OI': put_oi,
            'Call Pct Text': f"{c_pct}<br>{c_delta_str}".strip("<br>"),
            'Put Pct Text': f"{p_pct}<br>{p_delta_str}".strip("<br>"),
            'ATM IV': atm_iv, '25Δ Call': d25_c_iv, '25Δ Put': d25_p_iv, '10Δ Call': d10_c_iv, '10Δ Put': d10_p_iv,
            'Weighted IV': weighted_iv
        })

    omni_df = pd.DataFrame(omni_data)
    if not omni_df.empty:
        fig_omni = go.Figure()
        y_call, y_put = ('Call Vol', 'Put Vol') if bar_mode == "Volume (Flow)" else ('Call OI', 'Put OI')
        y_axis_title = 'Contract Volume' if bar_mode == "Volume (Flow)" else 'Open Interest'

        fig_omni.add_trace(go.Bar(x=omni_df['date_str'], y=omni_df[y_call], name=f'Call {bar_mode.split()[0]}', marker_color='#00CC96', opacity=0.3, yaxis='y1', text=omni_df['Call Pct Text'], textposition='inside'))
        fig_omni.add_trace(go.Bar(x=omni_df['date_str'], y=omni_df[y_put], name=f'Put {bar_mode.split()[0]}', marker_color='#EF553B', opacity=0.3, yaxis='y1', text=omni_df['Put Pct Text'], textposition='inside'))

        if show_10_delta:
            fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['10Δ Call'], name='<10Δ Call IV', mode='lines', line=dict(color='#00FF99', width=1, dash='dashdot'), yaxis='y2', opacity=0.6))
            fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['10Δ Put'], name='<10Δ Put IV', mode='lines', line=dict(color='#FF3366', width=1, dash='dashdot'), yaxis='y2', opacity=0.6))

        fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['25Δ Call'], name='25Δ Call IV', mode='lines', line=dict(color='#00664A', width=2, dash='dot'), yaxis='y2'))
        fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['25Δ Put'], name='25Δ Put IV', mode='lines', line=dict(color='#8B2211', width=2, dash='dot'), yaxis='y2'))
        fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['ATM IV'], name='ATM IV (Baseline)', mode='lines+markers', line=dict(color='#FFFFFF', width=3), yaxis='y2'))
        fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['Weighted IV'], name='OI-Weighted IV', mode='lines+markers', line=dict(color='#FECB52', width=4), yaxis='y2'))

        fig_omni.update_layout(template='plotly_dark', barmode='stack', height=600, hovermode='x unified',
                               yaxis=dict(title=y_axis_title, side='left', showgrid=False),
                               yaxis2=dict(title='Implied Volatility (%)', side='right', overlaying='y', showgrid=True),
                               legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"), margin=dict(b=80))
        fig_omni.update_xaxes(type='category', categoryorder='category ascending')
        st.plotly_chart(fig_omni, use_container_width=True)

# --- LOAD DATA ---

db_con, df_summary, bucket_name = init_db_and_summary()
if df_summary.empty or db_con is None: st.stop()

# --- GLOBALS & SIDEBAR ---
st.sidebar.title("Radar Controls")
selected_ticker = st.sidebar.selectbox("Select Asset:", df_summary['ticker'].unique())
st.sidebar.divider()
global_timeframe = st.sidebar.radio("Global Trend Scope:",
                                    ["20 Days (Daily)", "60 Days (Weekly)", "180 Days (Weekly)", "360 Days (Monthly)"])
st.sidebar.divider()

# --- MEGA PRE-COMPUTATION (SPEED FIX) ---
@st.cache_data(ttl=3600)
def process_ticker_data(selected_ticker, _con, bucket_name, _df_summary):
    t_summary = _df_summary[_df_summary['ticker'] == selected_ticker].copy()
    t_summary['date_str'] = t_summary['date'].astype(str).str[:10]

    # Predicate Pushdown: Dynamically query ONLY this ticker from the newly partitioned S3 dataset!
    try:
        t_chain = _con.execute(
            f"SELECT * FROM read_parquet('s3://{bucket_name}/dashboard_data/partitioned_chain_gold/ticker={selected_ticker}/*.parquet') "
            f"WHERE strftime(timestamp, '%Y-%m-%d') NOT IN {tuple(MARKET_HOLIDAYS)} "
            f"ORDER BY timestamp ASC"
        ).df()
    except Exception as e:
        st.error(f"Error fetching data for {selected_ticker}: {e}")
        return t_summary, pd.DataFrame()

    if t_chain.empty:
        return t_summary, t_chain

    t_chain['date_str'] = t_chain['timestamp'].astype(str).str[:10]
    t_chain['date_dt'] = pd.to_datetime(t_chain['date_str'])
    t_chain['exp_dt'] = pd.to_datetime(t_chain['expiration'])
    t_chain['dte'] = (t_chain['exp_dt'] - t_chain['date_dt']).dt.days

    t_chain['underlying_price'] = pd.to_numeric(t_chain['underlying_price'], errors='coerce')
    t_chain['last_price'] = pd.to_numeric(t_chain['last_price'], errors='coerce').fillna(0)
    t_chain['volume'] = pd.to_numeric(t_chain['volume'], errors='coerce').fillna(0)
    t_chain['open_interest'] = pd.to_numeric(t_chain['open_interest'], errors='coerce').fillna(0)
    t_chain['iv'] = pd.to_numeric(t_chain['iv'], errors='coerce')
    t_chain['delta'] = pd.to_numeric(t_chain['delta'], errors='coerce')
    t_chain['gamma'] = pd.to_numeric(t_chain['gamma'], errors='coerce')

    # Premium tracking
    t_chain['premium_vol'] = t_chain['volume'] * t_chain['last_price'] * 100
    t_chain['premium_oi'] = t_chain['open_interest'] * t_chain['last_price'] * 100
    return t_summary, t_chain

ticker_summary, ticker_chain = process_ticker_data(selected_ticker, db_con, bucket_name, df_summary)

available_dates = sorted(ticker_summary['date_str'].unique(), reverse=True)
selected_date = st.sidebar.selectbox("Select Date Snapshot:", available_dates)

current_chain = ticker_chain[ticker_chain['date_str'] == selected_date]
current_summary = ticker_summary[ticker_summary['date_str'] == selected_date]
spot_price = current_chain['underlying_price'].iloc[
    0] if not current_chain.empty and 'underlying_price' in current_chain.columns else 0

company_info = fetch_company_info(selected_ticker)
days_to_earnings = fetch_days_to_earnings(selected_ticker)

# --- HEADER ---
st.title(f"{company_info['name']} ({selected_ticker})")
h1, h2, h3 = st.columns([2, 1, 1])
with h1: st.markdown(f"**Snapshot:** {selected_date} | **Spot:** ${spot_price:,.2f}")
with h2: st.markdown(f"**Market Cap:** {company_info['market_cap']}")
with h3: st.markdown(f"**P/E Ratio:** {company_info['pe_ratio']}")
with st.expander("📖 Company Overview"): st.write(company_info['description'])
st.divider()

# --- EXEC METRICS ---
ts_sorted = ticker_summary.sort_values('date_str')
comp_date = selected_date
ts_20d = ts_sorted[pd.to_datetime(ts_sorted['date_str']) <= pd.to_datetime(comp_date)].tail(20).copy()

# Add daily total OI premium to the summary dataframe to calculate rank
daily_prem_oi = ticker_chain.groupby('date_str')['premium_oi'].sum().rename('total_prem_oi')
ts_20d = ts_20d.join(daily_prem_oi, on='date_str', how='left').fillna(0)

if 'call_volume' not in ts_20d.columns:
    ts_20d['call_volume'] = ts_20d['total_volume'] / (1 + ts_20d['put_call_ratio_vol'])
    ts_20d['put_volume'] = ts_20d['total_volume'] - ts_20d['call_volume']

row = current_summary.iloc[0] if not current_summary.empty else None

if row is not None:
    current_oi = current_chain['open_interest'].sum() if not current_chain.empty else 0
    prev_days = ticker_chain[ticker_chain['date_dt'] < pd.to_datetime(selected_date)]['date_dt'].unique()
    oi_change = 0
    if len(prev_days) > 0:
        prev_date = pd.to_datetime(sorted(prev_days, reverse=True)[0]).strftime('%Y-%m-%d')
        prev_oi = ticker_chain[ticker_chain['date_str'] == prev_date]['open_interest'].sum()
        oi_change = ((current_oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0

    vol_rank = (ts_20d['total_volume'] <= row['total_volume']).mean() * 100
    iv_rank = (ts_20d['oi_weighted_iv'] <= row['oi_weighted_iv']).mean() * 100

    # Calculate Premium Rank
    current_prem_val = daily_prem_oi.get(selected_date, 0)
    prem_rank = (ts_20d['total_prem_oi'] <= current_prem_val).mean() * 100

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("P/C Ratio", f"{row['put_call_ratio_vol']:.2f}")
    c2.metric("Change in OI", f"{oi_change:+.2f}%")
    c3.metric("Vol Rank", f"{vol_rank:.0f}%")
    c4.metric("IV Rank", f"{iv_rank:.0f}%")
    c5.metric("Prem Rank", f"{prem_rank:.0f}%")
    c6.metric("Earnings", days_to_earnings)
st.divider()

# --- TABS DEFINITION ---
st.sidebar.divider()
active_tab = st.sidebar.radio(
    "Select View:",
    ["🌊 Positioning", "📈 Volatility", "📍 Gamma/Delta", "📉 Short Volume", "🕵️ Accumulation", "🎯 Signals Testing", "⚡ Signals", "🏆 Trade Ideas", "🌡️ Surface Heatmap"]
)

# ==========================================
# TAB 1: POSITIONING
# ==========================================
if active_tab == "🌊 Positioning":
    st.subheader(f"Macro Trend Radar ({global_timeframe})")

    days_lookback = int(global_timeframe.split()[0])
    cutoff_date = pd.to_datetime(comp_date) - pd.Timedelta(days=days_lookback)

    t_sum = ticker_summary[pd.to_datetime(ticker_summary['date_str']) >= cutoff_date].copy()
    t_chain = ticker_chain[ticker_chain['date_dt'] >= cutoff_date].copy()

    if "Weekly" in global_timeframe:
        t_sum['plot_date'] = pd.to_datetime(t_sum['date']).dt.to_period('W-FRI').dt.end_time.dt.strftime('%Y-%m-%d')
        t_chain['plot_date'] = t_chain['date_dt'].dt.to_period('W-FRI').dt.end_time.dt.strftime('%Y-%m-%d')
    elif "Monthly" in global_timeframe:
        t_sum['plot_date'] = pd.to_datetime(t_sum['date']).dt.to_period('M').dt.end_time.dt.strftime('%Y-%m')
        t_chain['plot_date'] = t_chain['date_dt'].dt.to_period('M').dt.end_time.dt.strftime('%Y-%m')
    else:
        t_sum['plot_date'] = t_sum['date_str']
        t_chain['plot_date'] = t_chain['date_str']

    # ==========================================
    # ROW 1: MACRO VOLUME & OI HISTOGRAM
    # ==========================================
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.subheader("Volume Stack & P/C Ratio")
        if 'call_volume' not in t_sum.columns:
            t_sum['call_volume'] = t_sum['total_volume'] / (1 + t_sum['put_call_ratio_vol'])
            t_sum['put_volume'] = t_sum['total_volume'] - t_sum['call_volume']

        vol_agg = t_sum.groupby('plot_date').agg(
            {'call_volume': 'sum', 'put_volume': 'sum', 'total_volume': 'sum'}).reset_index()
        vol_agg['put_call_ratio_vol'] = np.where(vol_agg['call_volume'] > 0,
                                                 vol_agg['put_volume'] / vol_agg['call_volume'], 0)

        safe_tot_vol = np.where(vol_agg['total_volume'] == 0, 1, vol_agg['total_volume'])
        call_text = [f"{(c / safe_tot_vol[i] * 100):.0f}%" if c > 0 else "" for i, c in
                     enumerate(vol_agg['call_volume'])]
        put_text = [f"{(p / safe_tot_vol[i] * 100):.0f}%" if p > 0 else "" for i, p in enumerate(vol_agg['put_volume'])]

        fig_vol = go.Figure()
        fig_vol.add_trace(
            go.Bar(x=vol_agg['plot_date'], y=vol_agg['call_volume'], name='Call Vol', marker_color='#00CC96',
                   opacity=0.8, yaxis='y1', text=call_text, textposition='inside', insidetextanchor='middle'))
        fig_vol.add_trace(
            go.Bar(x=vol_agg['plot_date'], y=vol_agg['put_volume'], name='Put Vol', marker_color='#EF553B', opacity=0.8,
                   yaxis='y1', text=put_text, textposition='inside', insidetextanchor='middle'))
        fig_vol.add_trace(
            go.Scatter(x=vol_agg['plot_date'], y=vol_agg['put_call_ratio_vol'], name='P/C Ratio', mode='lines+markers',
                       line=dict(color='#FECB52', width=2), yaxis='y2'))

        fig_vol.update_layout(template='plotly_dark', barmode='stack',
                              yaxis2=dict(title="P/C Ratio", overlaying='y', side='right', range=[0, 2]),
                              legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                              margin=dict(t=50, b=80, l=10, r=10), height=400,
                              xaxis=dict(type='category', categoryorder='category ascending'))
        st.plotly_chart(fig_vol, use_container_width=True)

    with col_t2:
        st.subheader("Net Change in Open Interest Trend")
        c_oi_1, c_oi_2 = st.columns([2, 1])
        with c_oi_1:
            oi_chg_dte = st.radio("DTE Scope (ΔOI):",
                                  ["All Exps", "Front-Month (7-45 DTE)", "Long-Term (>45 DTE)", "Specific Expiration"],
                                  horizontal=True, label_visibility="collapsed")
        with c_oi_2:
            sel_oi_exp = render_two_step_selector("oi_chg_exp", sorted(t_chain['expiration'].dropna().unique()),
                                                  is_multi=False) if oi_chg_dte == "Specific Expiration" else None

        df_chg = t_chain.copy()
        if oi_chg_dte == "Specific Expiration" and sel_oi_exp:
            df_chg = filter_by_exp(df_chg, sel_oi_exp)
        elif "Front-Month" in oi_chg_dte:
            df_chg = df_chg[(df_chg['dte'] >= 7) & (df_chg['dte'] <= 45)]
        elif "Long-Term" in oi_chg_dte:
            df_chg = df_chg[df_chg['dte'] > 45]

        daily_oi = df_chg.groupby('date_str')['open_interest'].sum().reset_index()
        daily_oi['oi_change'] = daily_oi['open_interest'].diff().fillna(0)

        date_map = t_chain[['date_str', 'plot_date']].drop_duplicates()
        daily_oi = daily_oi.merge(date_map, on='date_str', how='left')
        plot_oi = daily_oi.groupby('plot_date').agg({'oi_change': 'sum', 'open_interest': 'last'}).reset_index()

        plot_oi['prev_oi'] = plot_oi['open_interest'].shift(1)
        plot_oi['oi_pct_change'] = np.where(plot_oi['prev_oi'] > 0, (plot_oi['oi_change'] / plot_oi['prev_oi']) * 100,
                                            0)
        plot_oi['text'] = [f"{x:+.1f}%" if x != 0 else "" for x in plot_oi['oi_pct_change']]

        fig_oi_chg = go.Figure()
        fig_oi_chg.add_trace(go.Bar(
            x=plot_oi['plot_date'],
            y=plot_oi['oi_change'],
            text=plot_oi['text'],
            textposition='outside',
            marker_color=np.where(plot_oi['oi_change'] >= 0, '#00CC96', '#EF553B'),
            hovertemplate="<b>Date:</b> %{x}<br><b>Δ OI:</b> %{y:+,d}<extra></extra>"
        ))
        fig_oi_chg.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5)
        fig_oi_chg.update_layout(template='plotly_dark', yaxis_title="Δ Open Interest",
                                 margin=dict(t=30, b=80, l=10, r=10), height=400,
                                 xaxis=dict(type='category', categoryorder='category ascending'))
        st.plotly_chart(fig_oi_chg, use_container_width=True)

    st.divider()

    # ==========================================
    # ROW 2: NEW PREMIUM CHARTS
    # ==========================================
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.subheader("Premium Stack by Expiration (Last x OI)")
        st.markdown("<span style='font-size:12px; color:#A0AEC0;'>Excludes Monday & Wednesday Expirations</span>",
                    unsafe_allow_html=True)

        # 1. Get valid expirations (Exclude Mon=0, Wed=2)
        all_exps = sorted(ticker_chain['expiration'].dropna().unique())
        valid_exps = [e for e in all_exps if pd.to_datetime(e).weekday() not in [0, 2]]

        # 2. Find closest index to selected date
        future_exps = [e for e in valid_exps if e >= selected_date]
        idx = valid_exps.index(future_exps[0]) if future_exps else len(valid_exps)

        # 3. Slice 10 backward, 10 forward
        start_idx = max(0, idx - 10)
        end_idx = min(len(valid_exps), idx + 10)
        target_exps = valid_exps[start_idx:end_idx]

        # 4. Gather Data
        prem_stack_data = []
        for e in target_exps:
            e_df = ticker_chain[(ticker_chain['expiration'] == e) & (ticker_chain['date_str'] <= selected_date)]
            if not e_df.empty:
                last_date = e_df['date_str'].max()  # Gets selected_date for future, or actual last trading day for past
                day_df = e_df[e_df['date_str'] == last_date]
                c_prem = day_df[day_df['side'] == 'CALL']['premium_oi'].sum()
                p_prem = day_df[day_df['side'] == 'PUT']['premium_oi'].sum()
                prem_stack_data.append(
                    {'Expiration': e, 'Call Premium': c_prem, 'Put Premium': p_prem, 'Total': c_prem + p_prem})

        df_prem_stack = pd.DataFrame(prem_stack_data)

        if not df_prem_stack.empty:
            df_prem_stack['put_call_ratio'] = np.where(df_prem_stack['Call Premium'] > 0,
                                                       df_prem_stack['Put Premium'] / df_prem_stack['Call Premium'], 0)

            fig_prem_stack = go.Figure()
            fig_prem_stack.add_trace(
                go.Bar(x=df_prem_stack['Expiration'], y=df_prem_stack['Call Premium'], name='Call Premium ($)',
                       marker_color='#00CC96', opacity=0.8, yaxis='y1'))
            fig_prem_stack.add_trace(
                go.Bar(x=df_prem_stack['Expiration'], y=df_prem_stack['Put Premium'], name='Put Premium ($)',
                       marker_color='#EF553B', opacity=0.8, yaxis='y1'))
            fig_prem_stack.add_trace(
                go.Scatter(x=df_prem_stack['Expiration'], y=df_prem_stack['put_call_ratio'], name='P/C Ratio (Premium)',
                           mode='lines+markers', line=dict(color='#FECB52', width=2), yaxis='y2'))

            fig_prem_stack.update_layout(template='plotly_dark', barmode='stack',
                                         yaxis=dict(title="Notional Premium ($)", side='left'),
                                         yaxis2=dict(title="P/C Premium Ratio", overlaying='y', side='right',
                                                     range=[0, 3]),
                                         legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                                         margin=dict(t=10, b=10, l=10, r=10), height=400,
                                         xaxis=dict(type='category', categoryorder='category ascending'))

            # FIXED: Calculate numerical categorical placement for the Snapshot Date line
            plot_exps = df_prem_stack['Expiration'].tolist()
            past_exps = [e for e in plot_exps if e <= selected_date]
            if past_exps:
                x_idx = plot_exps.index(past_exps[-1])
                x_pos = x_idx if past_exps[-1] == selected_date else x_idx + 0.5
            else:
                x_pos = -0.5

            # Add the vertical line using the calculated float index instead of the raw string
            fig_prem_stack.add_vline(x=x_pos, line_dash="solid", line_color="white", opacity=0.7,
                                     annotation_text="Snapshot Date")

            st.plotly_chart(fig_prem_stack, use_container_width=True)

    with col_p2:
        st.subheader("10-Day Leading Premium History")
        sel_hist_exp = render_two_step_selector("prem_hist_exp", sorted(ticker_chain['expiration'].dropna().unique()),
                                                is_multi=False)

        if sel_hist_exp:
            # Filter the chain for the selected expiration, ending at the selected date, get last 10 days
            hist_df = ticker_chain[ticker_chain['date_str'] <= selected_date].copy()
            hist_df = filter_by_exp(hist_df, sel_hist_exp)

            if not hist_df.empty:
                valid_dates = sorted(hist_df['date_str'].unique())[-10:]
                hist_df = hist_df[hist_df['date_str'].isin(valid_dates)]

                # Aggregate Call/Put Premium and grab the spot price for each day
                hist_agg_c = hist_df[hist_df['side'] == 'CALL'].groupby('date_str')['premium_oi'].sum().rename(
                    'Call Premium')
                hist_agg_p = hist_df[hist_df['side'] == 'PUT'].groupby('date_str')['premium_oi'].sum().rename(
                    'Put Premium')
                hist_spot = hist_df.groupby('date_str')['underlying_price'].first()

                hist_merged = pd.concat([hist_agg_c, hist_agg_p, hist_spot], axis=1).fillna(0).reset_index()

                fig_hist = make_subplots(specs=[[{"secondary_y": True}]])
                fig_hist.add_trace(go.Bar(x=hist_merged['date_str'], y=hist_merged['Call Premium'], name="Call Premium",
                                          marker_color='#00CC96'), secondary_y=False)
                fig_hist.add_trace(
                    go.Bar(x=hist_merged['date_str'], y=-hist_merged['Put Premium'], name="Put Premium (Inverted)",
                           marker_color='#EF553B'), secondary_y=False)
                fig_hist.add_trace(
                    go.Scatter(x=hist_merged['date_str'], y=hist_merged['underlying_price'], name="Spot Price",
                               mode='lines+markers', line=dict(color='white', width=2)), secondary_y=True)

                fig_hist.update_layout(template='plotly_dark', barmode='relative', hovermode='x unified',
                                       yaxis=dict(title="Notional Premium ($)", showgrid=False),
                                       yaxis2=dict(title="Spot Price", showgrid=False),
                                       legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                                       margin=dict(t=10, b=10, l=10, r=10), height=400,
                                       xaxis=dict(type='category', categoryorder='category ascending'))
                st.plotly_chart(fig_hist, use_container_width=True)
            else:
                st.warning("No historical data available for this expiration on or before the selected date.")

    st.divider()
    # ==========================================
    # ROW 3: PIE CHARTS
    # ==========================================
    c_pie1, c_pie2, c_pie_ctrl = st.columns([2, 2, 1])
    with c_pie_ctrl:
        st.subheader("Pie Controls")
        pie_unit = st.radio("Display Unit:", ["Notional Value ($)", "Contract Amount"], index=0)
        pie_scope = st.radio("DTE Scope (Pies):",
                             ["All Exps", "Front-Month (7-45 DTE)", "Long-Term (>45 DTE)", "Specific Expiration"])
        sel_pie_exp = render_two_step_selector("pie_exp", sorted(current_chain['expiration'].dropna().unique()),
                                               is_multi=False) if pie_scope == "Specific Expiration" else None

    df_pie = current_chain.copy()
    if not df_pie.empty:
        if pie_scope == "Specific Expiration" and sel_pie_exp:
            df_pie = filter_by_exp(df_pie, sel_pie_exp)
        elif "Front-Month" in pie_scope:
            df_pie = df_pie[(df_pie['dte'] >= 7) & (df_pie['dte'] <= 45)]
        elif "Long-Term" in pie_scope:
            df_pie = df_pie[df_pie['dte'] > 45]

        if pie_unit == "Notional Value ($)":
            df_pie['oi_val'] = df_pie['open_interest'] * df_pie['last_price'] * 100
            df_pie['vol_val'] = df_pie['volume'] * df_pie['last_price'] * 100
            h_temp = "%{label}<br>$%{value:,.0f}<extra></extra>"
        else:
            df_pie['oi_val'] = df_pie['open_interest']
            df_pie['vol_val'] = df_pie['volume']
            h_temp = "%{label}<br>%{value:,.0f} Contracts<extra></extra>"

        with c_pie1:
            st.subheader("Current Structural Capital (OI)")
            c_oi = df_pie[df_pie['side'] == 'CALL']['oi_val'].sum()
            p_oi = df_pie[df_pie['side'] == 'PUT']['oi_val'].sum()
            fig_oi = go.Figure(data=[
                go.Pie(labels=['Calls', 'Puts'], values=[c_oi, p_oi], marker_colors=['#00CC96', '#EF553B'],
                       hovertemplate=h_temp)])
            fig_oi.update_layout(template='plotly_dark', margin=dict(t=30, b=30, l=10, r=10), height=350)
            st.plotly_chart(fig_oi, use_container_width=True)

        with c_pie2:
            st.subheader("Cumulative Traded Flow (Volume)")
            c_vol = df_pie[df_pie['side'] == 'CALL']['vol_val'].sum()
            p_vol = df_pie[df_pie['side'] == 'PUT']['vol_val'].sum()
            fig_vol_pie = go.Figure(data=[
                go.Pie(labels=['Calls', 'Puts'], values=[c_vol, p_vol], marker_colors=['#00CC96', '#EF553B'],
                       hovertemplate=h_temp)])
            fig_vol_pie.update_layout(template='plotly_dark', margin=dict(t=30, b=30, l=10, r=10), height=350)
            st.plotly_chart(fig_vol_pie, use_container_width=True)

    st.divider()

    # ==========================================
    # ROW 4: VWKS & STRIKE PROFILE
    # ==========================================
    st.subheader("Strike Profile (+/- 20%)")
    c_sp_mode, c_sp_metric = st.columns(2)
    with c_sp_mode:
        sp_scope = st.radio("Profile Scope:", ["Global Scope (DTE)", "Specific Expiration"], horizontal=True,
                            label_visibility="collapsed")
    with c_sp_metric:
        sp_metric = st.radio("Metric:", ["Volume", "Open Interest"], horizontal=True, label_visibility="collapsed")

    if not current_chain.empty and spot_price > 0:
        sp_df = current_chain.copy()
        if sp_scope == "Specific Expiration":
            avail_exps = sorted(sp_df['expiration'].dropna().unique())
            selected_sp_exp = render_two_step_selector("sp_profile", avail_exps, is_multi=False)
            if selected_sp_exp: sp_df = filter_by_exp(sp_df, selected_sp_exp).copy()
        else:
            sp_dte = st.radio("DTE Scope (Profile):", ["All Exps", "Front-Month (7-45 DTE)", "Long-Term (>45 DTE)"],
                              horizontal=True)
            if "Front-Month" in sp_dte:
                sp_df = sp_df[(sp_df['dte'] >= 7) & (sp_df['dte'] <= 45)]
            elif "Long-Term" in sp_dte:
                sp_df = sp_df[sp_df['dte'] > 45]

        sp_df = sp_df[(sp_df['strike'] >= spot_price * 0.8) & (sp_df['strike'] <= spot_price * 1.2)]
        if not sp_df.empty:
            y_col = 'volume' if sp_metric == "Volume" else 'open_interest'
            sp_agg = sp_df.groupby(['strike', 'side'])[y_col].sum().reset_index()
            fig_sp = px.bar(sp_agg, x='strike', y=y_col, color='side', barmode='group', template='plotly_dark',
                            color_discrete_map={'CALL': '#00CC96', 'PUT': '#EF553B'})
            fig_sp.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text="Spot")
            fig_sp.update_layout(yaxis_title=sp_metric, xaxis_title="Strike Price", hovermode='x unified',
                                 margin=dict(t=30, b=10, l=10, r=10),
                                 legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
            st.plotly_chart(fig_sp, use_container_width=True)

    st.divider()

    dates = sorted(ticker_chain['date_str'].dropna().unique())
    if len(dates) >= 2:
        today_str = selected_date
        curr_idx = dates.index(today_str) if today_str in dates else 0
        yest_str = dates[curr_idx + 1] if curr_idx + 1 < len(dates) else None
    else:
        today_str, yest_str = selected_date, None

# ==========================================
# TAB 2: VOLATILITY
# ==========================================
if active_tab == "📈 Volatility":
    render_omni_volatility(ticker_chain, ts_20d, key_suffix="tab2")

    st.divider()

    # ==========================================
    # INDIVIDUAL CONTRACT IV TRACKER
    # ==========================================
    st.subheader("Specific Contract IV Tracker")
    df_tracker = ticker_chain[ticker_chain['date_str'].isin(ts_20d['date_str'].unique())].copy()

    if not df_tracker.empty:
        df_tracker['contract_label'] = df_tracker['expiration'].astype(str) + " | " + df_tracker['side'].astype(
            str) + " | $" + df_tracker['strike'].astype(str)

        c_m, c_e, c_s, c_sd = st.columns(4)
        f_months = c_m.multiselect("1. Filter Month(s):",
                                   sorted(list(set([e[:7] for e in df_tracker['expiration'].dropna().unique()]))))
        df_f1 = df_tracker[df_tracker['expiration'].str[:7].isin(f_months)] if f_months else df_tracker
        f_exps = c_e.multiselect("2. Filter Expiration(s):", sorted(df_f1['expiration'].dropna().unique()))
        df_f2 = df_f1[df_f1['expiration'].isin(f_exps)] if f_exps else df_f1
        f_strikes = c_s.multiselect("3. Filter Strike(s):", sorted(df_f2['strike'].dropna().unique()))
        df_f3 = df_f2[df_f2['strike'].isin(f_strikes)] if f_strikes else df_f2
        f_sides = c_sd.multiselect("4. Filter Side:", ["CALL", "PUT"])
        df_f4 = df_f3[df_f3['side'].isin(f_sides)] if f_sides else df_f3

        safe_options = sorted(
            list(set(df_f4['contract_label'].unique()).union(set(st.session_state.get('iv_tracker_select', [])))))
        selected_contracts = st.multiselect("5. Select Contracts to Compare:", options=safe_options,
                                            default=st.session_state.get('iv_tracker_select', []),
                                            key='iv_tracker_select')

        if selected_contracts:
            contract_data = df_tracker[df_tracker['contract_label'].isin(selected_contracts)].sort_values('date_str')
            contract_data['iv_pct'] = pd.to_numeric(contract_data['iv'], errors='coerce') * 100

            fig_iv_track = make_subplots(specs=[[{"secondary_y": True}]])
            colors = px.colors.qualitative.Plotly
            for i, c_label in enumerate(selected_contracts):
                c_df = contract_data[contract_data['contract_label'] == c_label]
                col = colors[i % len(colors)]
                fig_iv_track.add_trace(
                    go.Scatter(x=c_df['date_str'], y=c_df['iv_pct'], name=f"IV: {c_label}", mode='lines+markers',
                               line=dict(color=col, width=2)), secondary_y=False)
                fig_iv_track.add_trace(
                    go.Bar(x=c_df['date_str'], y=c_df['volume'], name=f"Vol: {c_label}", marker_color=col,
                           opacity=0.25), secondary_y=True)

            fig_iv_track.update_xaxes(type='category', categoryorder='category ascending')
            fig_iv_track.update_layout(title="Historical IV & Volume by Contract", template='plotly_dark',
                                       barmode='stack', hovermode='x unified',
                                       yaxis=dict(title="Implied Volatility (%)", showgrid=False),
                                       yaxis2=dict(title="Volume", showgrid=False),
                                       legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                                       margin=dict(t=40, b=10, l=10, r=10), height=500)
            st.plotly_chart(fig_iv_track, use_container_width=True)

    st.divider()
    # ==========================================
    # CURRENT IV SMILE & VOLUME PROFILE
    # ==========================================
    st.subheader("Current IV Smile & Volume Profile")
    if not current_chain.empty and spot_price > 0:
        exps = sorted(current_chain['expiration'].unique())
        smile_exps = render_two_step_selector("iv_smile", exps, is_multi=True)

        if smile_exps:
            smile_df = current_chain[current_chain['expiration'].isin(smile_exps)].copy()
            smile_df = smile_df[(smile_df['strike'] >= spot_price * 0.8) & (smile_df['strike'] <= spot_price * 1.2)]

            if not smile_df.empty:
                agg_smile = smile_df.groupby(['strike', 'expiration']).agg(
                    {'iv': 'mean', 'volume': 'sum'}).reset_index()
                agg_smile['iv_pct'] = agg_smile['iv'] * 100

                fig_smile = go.Figure()
                colors = px.colors.qualitative.Plotly

                for i, exp in enumerate(smile_exps):
                    exp_data = agg_smile[agg_smile['expiration'] == exp]
                    c = colors[i % len(colors)]
                    formatted_label = get_exp_label(exp)

                    fig_smile.add_trace(
                        go.Bar(x=exp_data['strike'], y=exp_data['volume'], name=f'Vol {formatted_label}',
                               marker_color=c, opacity=0.35, yaxis='y1', offsetgroup=str(i))
                    )
                    fig_smile.add_trace(
                        go.Scatter(x=exp_data['strike'], y=exp_data['iv_pct'], name=f'IV {formatted_label}',
                                   mode='lines+markers', line=dict(color=c, width=2), yaxis='y2')
                    )

                fig_smile.update_layout(
                    title="Strike Liquidity vs. Implied Volatility (Smile)", template='plotly_dark', barmode='group',
                    yaxis=dict(title='Volume', side='left', showgrid=False),
                    yaxis2=dict(title='Implied Volatility (%)', side='right', overlaying='y', showgrid=True),
                    hovermode='x unified', legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                    margin=dict(t=40, b=10, l=10, r=10)
                )
                fig_smile.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text="Spot")
                st.plotly_chart(fig_smile, use_container_width=True)
            else:
                st.warning("No data within 20% of the spot price for the selected expirations.")

    st.divider()
    # ==========================================
    # IV TERM STRUCTURE
    # ==========================================
    st.subheader("IV Term Structure (Contango vs Backwardation)")

    c_ts_mode, c_ts_metric, c_ts_filter = st.columns([2, 1.5, 1])
    with c_ts_mode:
        ts_mode = st.radio("Term Structure View:",
                           ["Current Profile (Wings vs ATM)", "Historical Shift (Curve Changes)"], horizontal=True,
                           label_visibility="collapsed")
    with c_ts_metric:
        ts_bar_metric = st.radio("Background Bars:", ["Open Interest", "Volume"], horizontal=True,
                                 label_visibility="collapsed")
    with c_ts_filter:
        ts_exclude_short = st.checkbox("Exclude ≤ 7 DTE", value=True)

    if not ticker_chain.empty and spot_price > 0:
        fig_ts = go.Figure()

        if "Current Profile" in ts_mode:
            ts_data = []
            for exp in sorted(current_chain['expiration'].unique()):
                exp_df = current_chain[current_chain['expiration'] == exp].copy()
                if ts_exclude_short and exp_df['dte'].iloc[0] <= 7: continue

                exp_df['strike_dist'] = (exp_df['strike'] - spot_price).abs()
                atm_iv = exp_df[exp_df['strike'] == exp_df.loc[exp_df['strike_dist'].idxmin(), 'strike']]['iv'].mean()

                calls, puts = exp_df[exp_df['side'] == 'CALL'], exp_df[exp_df['side'] == 'PUT']
                d25_c_iv = calls[(calls['delta'] >= 0.20) & (calls['delta'] <= 0.30)]['iv'].mean()
                d25_p_iv = puts[(puts['delta'] <= -0.20) & (puts['delta'] >= -0.30)]['iv'].mean()
                c_oi, p_oi = calls['open_interest'].sum(), puts['open_interest'].sum()
                c_vol, p_vol = calls['volume'].sum(), puts['volume'].sum()

                ts_data.append({
                    'Expiration': exp, 'ATM IV': atm_iv * 100 if pd.notna(atm_iv) else np.nan,
                    '25Δ Call IV': d25_c_iv * 100 if pd.notna(d25_c_iv) else np.nan,
                    '25Δ Put IV': d25_p_iv * 100 if pd.notna(d25_p_iv) else np.nan,
                    'Call OI': c_oi, 'Put OI': p_oi, 'Call Vol': c_vol, 'Put Vol': p_vol
                })

            ts_df = pd.DataFrame(ts_data).dropna(subset=['ATM IV'])
            if not ts_df.empty:
                y_c_bar = 'Call OI' if ts_bar_metric == "Open Interest" else 'Call Vol'
                y_p_bar = 'Put OI' if ts_bar_metric == "Open Interest" else 'Put Vol'

                fig_ts.add_trace(go.Bar(x=ts_df['Expiration'], y=ts_df[y_c_bar], name=f'Call {ts_bar_metric}',
                                        marker_color='#00CC96', opacity=0.25, yaxis='y2'))
                fig_ts.add_trace(
                    go.Bar(x=ts_df['Expiration'], y=ts_df[y_p_bar], name=f'Put {ts_bar_metric}', marker_color='#EF553B',
                           opacity=0.25, yaxis='y2'))
                fig_ts.add_trace(
                    go.Scatter(x=ts_df['Expiration'], y=ts_df['ATM IV'], name='ATM IV', mode='lines+markers',
                               line=dict(color='#FFFFFF', width=3), yaxis='y1'))
                fig_ts.add_trace(go.Scatter(x=ts_df['Expiration'], y=ts_df['25Δ Call IV'], name='25Δ Call Skew',
                                            mode='lines+markers', line=dict(color='#00CC96', width=2, dash='dot'),
                                            yaxis='y1'))
                fig_ts.add_trace(
                    go.Scatter(x=ts_df['Expiration'], y=ts_df['25Δ Put IV'], name='25Δ Put Skew', mode='lines+markers',
                               line=dict(color='#EF553B', width=2, dash='dot'), yaxis='y1'))

        else:
            avail_dates = sorted(ticker_chain['date_str'].unique(), reverse=True)
            curr_idx = avail_dates.index(selected_date) if selected_date in avail_dates else 0
            shift_dates = {'Today': selected_date,
                           '1 Day Ago': avail_dates[curr_idx + 1] if curr_idx + 1 < len(avail_dates) else None,
                           '1 Week Ago': avail_dates[curr_idx + 5] if curr_idx + 5 < len(avail_dates) else None}
            colors = {'Today': '#00CC96', '1 Day Ago': '#FECB52', '1 Week Ago': '#EF553B'}

            for label, d in shift_dates.items():
                if d is None: continue
                d_df = ticker_chain[ticker_chain['date_str'] == d].copy()
                d_spot = d_df['underlying_price'].iloc[0] if not d_df.empty else 0
                if d_spot == 0: continue

                d_ts_data = []
                for exp in sorted(d_df['expiration'].unique()):
                    exp_df = d_df[d_df['expiration'] == exp].copy()
                    if ts_exclude_short and exp_df['dte'].iloc[0] <= 7: continue
                    exp_df['strike_dist'] = (exp_df['strike'] - d_spot).abs()
                    atm_iv = exp_df[exp_df['strike'] == exp_df.loc[exp_df['strike_dist'].idxmin(), 'strike']][
                        'iv'].mean()
                    calls, puts = exp_df[exp_df['side'] == 'CALL'], exp_df[exp_df['side'] == 'PUT']

                    d_ts_data.append({
                        'Expiration': exp, 'ATM IV': atm_iv * 100 if pd.notna(atm_iv) else np.nan,
                        'Call OI': calls['open_interest'].sum(), 'Put OI': puts['open_interest'].sum(),
                        'Call Vol': calls['volume'].sum(), 'Put Vol': puts['volume'].sum()
                    })

                d_ts_df = pd.DataFrame(d_ts_data).dropna(subset=['ATM IV'])
                if not d_ts_df.empty:
                    if label == 'Today':
                        y_c_bar = 'Call OI' if ts_bar_metric == "Open Interest" else 'Call Vol'
                        y_p_bar = 'Put OI' if ts_bar_metric == "Open Interest" else 'Put Vol'
                        fig_ts.add_trace(
                            go.Bar(x=d_ts_df['Expiration'], y=d_ts_df[y_c_bar], name=f'Call {ts_bar_metric} (Current)',
                                   marker_color='#00CC96', opacity=0.25, yaxis='y2'))
                        fig_ts.add_trace(
                            go.Bar(x=d_ts_df['Expiration'], y=d_ts_df[y_p_bar], name=f'Put {ts_bar_metric} (Current)',
                                   marker_color='#EF553B', opacity=0.25, yaxis='y2'))

                    fig_ts.add_trace(go.Scatter(x=d_ts_df['Expiration'], y=d_ts_df['ATM IV'], name=f"{label} ({d})",
                                                mode='lines+markers',
                                                line=dict(color=colors[label], width=3 if label == 'Today' else 2),
                                                yaxis='y1'))

        if len(fig_ts.data) > 0:
            fig_ts.update_layout(template='plotly_dark', barmode='stack', hovermode='x unified',
                                 legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                                 margin=dict(t=30, b=10, l=10, r=10),
                                 yaxis=dict(title="Implied Volatility (%)", side='left', showgrid=False),
                                 yaxis2=dict(title=f"Total {ts_bar_metric}", side='right', overlaying='y',
                                             showgrid=False))
            fig_ts.update_xaxes(type='category', categoryorder='category ascending')
            st.plotly_chart(fig_ts, use_container_width=True)

# ==========================================
# TAB 3: GAMMA & DELTA (Exposure Profiles)
# ==========================================
if active_tab == "📍 Gamma/Delta":
    st.subheader("Gamma Exposure Profile (GEX)")
    c_g_model, c_g_view, c_g_dte, c_g_sel = st.columns([1.2, 1, 1.5, 1])
    with c_g_model:
        gamma_model = st.radio("Gamma Model:", ["Standard GEX", "Flow Proxy"], horizontal=True,
                               label_visibility="collapsed")
    with c_g_view:
        gamma_view = st.radio("Display View (Gamma):", ["Net", "Absolute"], horizontal=True,
                              label_visibility="collapsed")
    with c_g_dte:
        gamma_dte = st.radio("DTE Scope (Gamma):",
                             ["All Exps", "Front-Month (7-45 DTE)", "Long-Term (>45 DTE)", "Specific Expiration"],
                             horizontal=True, label_visibility="collapsed")
    with c_g_sel:
        sel_gamma_exp = render_two_step_selector("gamma_exp", sorted(current_chain['expiration'].dropna().unique()),
                                                 is_multi=False) if gamma_dte == "Specific Expiration" else None

    chain_gex = current_chain.copy()
    if gamma_dte == "Specific Expiration" and sel_gamma_exp:
        chain_gex = filter_by_exp(chain_gex, sel_gamma_exp)
    elif "Front-Month" in gamma_dte:
        chain_gex = chain_gex[(chain_gex['dte'] >= 7) & (chain_gex['dte'] <= 45)]
    elif "Long-Term" in gamma_dte:
        chain_gex = chain_gex[chain_gex['dte'] > 45]

    chain_gex = chain_gex[(chain_gex['strike'] >= spot_price * 0.8) & (chain_gex['strike'] <= spot_price * 1.2)]

    if not chain_gex.empty:
        fig_g = go.Figure()
        if "Standard" in gamma_model:
            chain_gex['gex'] = np.where(chain_gex['side'] == 'CALL',
                                        chain_gex['gamma'] * chain_gex['open_interest'] * 100 * spot_price,
                                        -chain_gex['gamma'] * chain_gex['open_interest'] * 100 * spot_price)

            if "Absolute" in gamma_view:
                agg_g = chain_gex.groupby(['strike', 'side'])['gex'].sum().reset_index()
                fig_g.add_trace(
                    go.Bar(x=agg_g[agg_g['side'] == 'CALL']['strike'], y=agg_g[agg_g['side'] == 'CALL']['gex'],
                           name='Call GEX (+)', marker_color='#00CC96'))
                fig_g.add_trace(
                    go.Bar(x=agg_g[agg_g['side'] == 'PUT']['strike'], y=agg_g[agg_g['side'] == 'PUT']['gex'],
                           name='Put GEX (-)', marker_color='#EF553B'))
                fig_g.update_layout(barmode='relative')
            else:
                agg_g = chain_gex.groupby('strike')['gex'].sum().reset_index()
                fig_g.add_trace(go.Bar(x=agg_g['strike'], y=agg_g['gex'], name='Net GEX',
                                       marker_color=np.where(agg_g['gex'] > 0, '#00CC96', '#EF553B')))
        else:
            prev_date = sorted(ticker_chain['date_str'].unique(), reverse=True)[1] if len(
                ticker_chain['date_str'].unique()) > 1 else None
            if prev_date:
                regime = chain_gex.merge(
                    ticker_chain[ticker_chain['date_str'] == prev_date][['expiration', 'strike', 'side', 'iv']].rename(
                        columns={'iv': 'p_iv'}), on=['expiration', 'strike', 'side'], how='left')
                regime = regime.dropna(subset=['iv', 'p_iv', 'open_interest'])
                if not regime.empty:
                    regime['gex'] = -((regime['iv'] - regime['p_iv']) * 100) * regime['open_interest']
                    if "Absolute" in gamma_view:
                        regime['type'] = np.where(regime['gex'] > 0, 'Sticky (+)', 'Slippery (-)')
                        agg_g = regime.groupby(['strike', 'type'])['gex'].sum().reset_index()
                        fig_g.add_trace(go.Bar(x=agg_g[agg_g['type'] == 'Sticky (+)']['strike'],
                                               y=agg_g[agg_g['type'] == 'Sticky (+)']['gex'], name='Sticky (+)',
                                               marker_color='#00CC96'))
                        fig_g.add_trace(go.Bar(x=agg_g[agg_g['type'] == 'Slippery (-)']['strike'],
                                               y=agg_g[agg_g['type'] == 'Slippery (-)']['gex'], name='Slippery (-)',
                                               marker_color='#EF553B'))
                        fig_g.update_layout(barmode='relative')
                    else:
                        agg_g = regime.groupby('strike')['gex'].sum().reset_index()
                        fig_g.add_trace(go.Bar(x=agg_g['strike'], y=agg_g['gex'], name='Net Flow Proxy',
                                               marker_color=np.where(agg_g['gex'] > 0, '#00CC96', '#EF553B')))

        if len(fig_g.data) > 0:
            if spot_price > 0: fig_g.add_vline(x=spot_price, line_dash="dash", line_color="white",
                                               annotation_text="Spot")
            fig_g.update_layout(template='plotly_dark', xaxis_title="Strike Price",
                                yaxis_title="Notional Gamma Exposure ($)" if "Standard" in gamma_model else "Flow Gamma (OI x ΔIV)",
                                hovermode='x unified', legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                                margin=dict(b=80))
            st.plotly_chart(fig_g, use_container_width=True)

    st.divider()

    st.subheader("Delta Exposure Profile (DEX)")
    c_d_view, c_d_dte, c_d_sel = st.columns([1, 1.5, 1])
    with c_d_view:
        delta_view = st.radio("Display View (Delta):", ["Net", "Absolute"], horizontal=True,
                              label_visibility="collapsed")
    with c_d_dte:
        delta_dte = st.radio("DTE Scope (Delta):",
                             ["All Exps", "Front-Month (7-45 DTE)", "Long-Term (>45 DTE)", "Specific Expiration"],
                             horizontal=True, label_visibility="collapsed")
    with c_d_sel:
        sel_delta_exp = render_two_step_selector("delta_exp", sorted(current_chain['expiration'].dropna().unique()),
                                                 is_multi=False) if delta_dte == "Specific Expiration" else None

    chain_dex = current_chain.copy()
    if delta_dte == "Specific Expiration" and sel_delta_exp:
        chain_dex = filter_by_exp(chain_dex, sel_delta_exp)
    elif "Front-Month" in delta_dte:
        chain_dex = chain_dex[(chain_dex['dte'] >= 7) & (chain_dex['dte'] <= 45)]
    elif "Long-Term" in delta_dte:
        chain_dex = chain_dex[chain_dex['dte'] > 45]

    chain_dex = chain_dex[(chain_dex['strike'] >= spot_price * 0.8) & (chain_dex['strike'] <= spot_price * 1.2)]

    if not chain_dex.empty:
        chain_dex['dex'] = np.where(chain_dex['side'] == 'CALL',
                                    chain_dex['delta'].abs() * chain_dex['open_interest'] * 100 * spot_price,
                                    -chain_dex['delta'].abs() * chain_dex['open_interest'] * 100 * spot_price)

        fig_d = go.Figure()
        if "Absolute" in delta_view:
            agg_d = chain_dex.groupby(['strike', 'side'])['dex'].sum().reset_index()
            fig_d.add_trace(go.Bar(x=agg_d[agg_d['side'] == 'CALL']['strike'], y=agg_d[agg_d['side'] == 'CALL']['dex'],
                                   name='Call DEX (+)', marker_color='#00CC96'))
            fig_d.add_trace(go.Bar(x=agg_d[agg_d['side'] == 'PUT']['strike'], y=agg_d[agg_d['side'] == 'PUT']['dex'],
                                   name='Put DEX (-)', marker_color='#EF553B'))
            fig_d.update_layout(barmode='relative')
        else:
            agg_d = chain_dex.groupby('strike')['dex'].sum().reset_index()
            fig_d.add_trace(go.Bar(x=agg_d['strike'], y=agg_d['dex'], name='Net DEX',
                                   marker_color=np.where(agg_d['dex'] > 0, '#00CC96', '#EF553B')))

        if spot_price > 0: fig_d.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text="Spot")
        fig_d.update_layout(template='plotly_dark', xaxis_title="Strike Price",
                            yaxis_title="Notional Delta Exposure ($)", hovermode='x unified',
                            legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"), margin=dict(b=80))
        st.plotly_chart(fig_d, use_container_width=True)



    # ==========================================
    # DEALER GAMMA & DELTA PROFILES
    # ==========================================
    st.divider()
    st.subheader("Dealer Implied Gamma Profile")
    st.markdown("Displays the net dealer gamma assuming dealers are short both calls and puts (Calls +, Puts -).")
    
    prof_chain = current_chain.copy()
    if delta_dte == "Specific Expiration" and sel_delta_exp:
        prof_chain = filter_by_exp(prof_chain, sel_delta_exp)
    elif "Front-Month" in delta_dte:
        prof_chain = prof_chain[(prof_chain['dte'] >= 7) & (prof_chain['dte'] <= 45)]
    elif "Long-Term" in delta_dte:
        prof_chain = prof_chain[prof_chain['dte'] > 45]
        
    if not prof_chain.empty and spot_price > 0:
        spot_range = np.linspace(spot_price * 0.85, spot_price * 1.15, 60)
        S = spot_range
        K = prof_chain['strike'].to_numpy(dtype=float)[:, np.newaxis]
        T = prof_chain['dte'].to_numpy(dtype=float)[:, np.newaxis] / 365.0
        sigma = prof_chain['iv'].to_numpy(dtype=float)[:, np.newaxis]
        is_call = (prof_chain['side'] == 'CALL').to_numpy(dtype=bool)[:, np.newaxis]
        oi = prof_chain['open_interest'].to_numpy(dtype=float)[:, np.newaxis]
        
        gamma_mat = bs_gamma(S[np.newaxis, :], K, T, 0.05, sigma)
        sign_mat = np.where(is_call, 1, -1)
        gex_mat = sign_mat * gamma_mat * oi * 100 * (S[np.newaxis, :]**2) * 0.01
        net_gex_curve = np.sum(gex_mat, axis=0)
        
        flip_point = None
        for i in range(len(net_gex_curve)-1):
            if net_gex_curve[i] * net_gex_curve[i+1] <= 0:
                m = (net_gex_curve[i+1] - net_gex_curve[i]) / (S[i+1] - S[i])
                if m != 0:
                    flip_point = S[i] - net_gex_curve[i] / m
                break
                
        fig_prof = go.Figure()
        fig_prof.add_trace(go.Scatter(x=S, y=net_gex_curve, mode='lines', fill='tozeroy', 
            fillcolor='rgba(0, 204, 150, 0.2)', line=dict(color='#00CC96', width=3), name='Net Dealer Gamma'))
        
        fig_prof.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text=f"Spot: {spot_price:.2f}")
        if flip_point:
            fig_prof.add_vline(x=flip_point, line_dash="dot", line_color="#FECB52", annotation_text=f"Flip: {flip_point:.2f}")
            
        fig_prof.update_layout(template='plotly_dark', title="Dealer Gamma Profile ($ per 1% Spot Move)",
                               xaxis_title="Simulated Spot Price", yaxis_title="Net Dealer GEX ($)")
        st.plotly_chart(fig_prof, use_container_width=True)
        
    st.divider()
    st.subheader("Dealer Implied Delta Profile")
    st.markdown("Displays the net structural delta across simulated spot prices.")
    
    if not prof_chain.empty and spot_price > 0:
        delta_mat = bs_delta(S[np.newaxis, :], K, T, 0.05, sigma, is_call)
        
        # Net Delta is Call Delta + Put Delta (put delta is already negative)
        dex_mat = delta_mat * oi * 100 * S[np.newaxis, :]
        net_dex_curve = np.sum(dex_mat, axis=0)
        
        flip_dex = None
        for i in range(len(net_dex_curve)-1):
            if net_dex_curve[i] * net_dex_curve[i+1] <= 0:
                m = (net_dex_curve[i+1] - net_dex_curve[i]) / (S[i+1] - S[i])
                if m != 0:
                    flip_dex = S[i] - net_dex_curve[i] / m
                break
                
        fig_dex = go.Figure()
        fig_dex.add_trace(go.Scatter(x=S, y=net_dex_curve, mode='lines', fill='tozeroy', 
            fillcolor='rgba(239, 85, 59, 0.2)', line=dict(color='#EF553B', width=3), name='Net Dealer Delta'))
            
        fig_dex.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text=f"Spot: {spot_price:.2f}")
        if flip_dex:
            fig_dex.add_vline(x=flip_dex, line_dash="dot", line_color="#FECB52", annotation_text=f"Zero Delta: {flip_dex:.2f}")
            
        fig_dex.update_layout(template='plotly_dark', title="Dealer Delta Profile (Notional DEX $)",
                               xaxis_title="Simulated Spot Price", yaxis_title="Net Dealer DEX ($)")
        st.plotly_chart(fig_dex, use_container_width=True)

# ==========================================
# TAB 7: STEALTH ACCUMULATION VISUALIZER
# ==========================================
if active_tab == "🕵️ Accumulation":
    st.header("🕵️ Stealth Accumulation Radar")
    st.markdown("Visualizing leading indicators of institutional positioning before underlying price breakouts.")

    # Dynamic lookback slider (Defaults to the most recent 40 trading days)
    all_dates = sorted(ticker_chain['date_str'].unique())
    if len(all_dates) == 0:
        st.warning("No historical data available.")
    else:
        default_start = all_dates[-40] if len(all_dates) >= 40 else all_dates[0]
        default_end = all_dates[-1]

        start_date, end_date = st.select_slider(
            "Select Global Accumulation Window Range:",
            options=all_dates,
            value=(default_start, default_end)
        )

        # Slice dataset globally based on user interactive window selection
        t_hist = ticker_chain[(ticker_chain['date_str'] >= start_date) & (ticker_chain['date_str'] <= end_date)].copy()

        if t_hist.empty:
            st.warning("Insufficient historical data inside selected date window to render trends.")
        else:
            # 0. Global Pre-calculations for accurate smoothing and percentiles
            global_spot = ticker_chain.groupby('date_str')['underlying_price'].first().reset_index()
            global_spot['Spot_3D_MA'] = global_spot['underlying_price'].rolling(window=3, min_periods=1).mean()
            spot_ma_dict = dict(zip(global_spot['date_str'], global_spot['Spot_3D_MA']))

            t_hist['strike_dist'] = (t_hist['strike'] - t_hist['underlying_price']).abs()
            spot_hist = t_hist.groupby('date_str')['underlying_price'].first()

            # Calculate the static 90-Day Percentile Bands for the New Scatter Chart
            past_dates = [d for d in all_dates if d <= end_date]
            dates_90 = past_dates[-90:] if len(past_dates) >= 90 else past_dates

            df_90 = ticker_chain[(ticker_chain['date_str'].isin(dates_90)) & (ticker_chain['side'] == 'CALL') & (
                ticker_chain['dte'].between(7, 45))].copy()
            df_90['vwks_num'] = df_90['strike'] * df_90['volume']
            vwks_90 = df_90.groupby('date_str').apply(
                lambda x: (x['vwks_num'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename(
                'VWKS').reset_index()
            vwks_90['VWKS_3D_MA'] = vwks_90['VWKS'].rolling(3, min_periods=1).mean()
            vwks_90['Spot_3D_MA'] = vwks_90['date_str'].map(spot_ma_dict)
            vwks_90['gap_pct'] = ((vwks_90['VWKS_3D_MA'] - vwks_90['Spot_3D_MA']) / vwks_90['Spot_3D_MA']) * 100

            # The flat static lines based on 90-day history
            gap_80th = vwks_90['gap_pct'].quantile(0.80)
            gap_20th = vwks_90['gap_pct'].quantile(0.20)

            # ==========================================
            # 1. THE MASTER ACCUMULATION RADAR (OVERLAY)
            # ==========================================
            st.divider()
            st.subheader("1. The Master Accumulation Radar")
            c_master, c_master_desc = st.columns([2.5, 1])
            with c_master:
                df_vwks = t_hist[(t_hist['side'] == 'CALL') & (t_hist['dte'].between(7, 45))].copy()
                df_vwks['vwks_num'] = df_vwks['strike'] * df_vwks['volume']
                agg_vwks = df_vwks.groupby('date_str').apply(
                    lambda x: (x['vwks_num'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename(
                    'VWKS').reset_index()
                agg_vwks['VWKS_3D_MA'] = agg_vwks['VWKS'].rolling(window=3, min_periods=1).mean()

                df_skew = t_hist[(t_hist['dte'].between(7, 60)) & (t_hist['iv'] > 0) & (t_hist['iv'] < 2.0)]
                calls_25 = \
                df_skew[(df_skew['side'] == 'CALL') & (df_skew['delta'].between(0.2, 0.3))].groupby('date_str')[
                    'iv'].mean()
                puts_25 = \
                df_skew[(df_skew['side'] == 'PUT') & (df_skew['delta'].between(-0.3, -0.2))].groupby('date_str')[
                    'iv'].mean()
                skew_spread = ((calls_25 - puts_25) * 100).rename("Skew").reset_index()
                skew_spread['Skew_3D_MA'] = skew_spread['Skew'].rolling(window=3, min_periods=1).mean()

                master_df = agg_vwks[['date_str', 'VWKS_3D_MA']].merge(skew_spread[['date_str', 'Skew_3D_MA']],
                                                                       on='date_str', how='outer').sort_values(
                    'date_str')

                fig1 = go.Figure()
                fig1.add_trace(
                    go.Scatter(x=master_df['date_str'], y=master_df['Skew_3D_MA'], name="3D MA Skew (%)", mode='lines',
                               line=dict(color='#FECB52', width=2.5), yaxis='y2'))
                fig1.add_trace(go.Scatter(x=master_df['date_str'], y=master_df['VWKS_3D_MA'], name="3D MA VWKS ($)",
                                          mode='lines+markers', line=dict(color='#00CC96', width=3), yaxis='y1'))
                fig1.add_trace(go.Scatter(x=spot_hist.index, y=spot_hist.values, name="Spot Price ($)", mode='lines',
                                          line=dict(color='white', width=2, dash='dot'), yaxis='y1'))

                fig1.update_layout(template='plotly_dark', height=450, margin=dict(l=10, r=10, t=10, b=10),
                                   hovermode='x unified',
                                   yaxis=dict(title="Price ($)", side='left', showgrid=False),
                                   yaxis2=dict(title="Skew (%)", side='right', overlaying='y', showgrid=False),
                                   legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
                fig1.update_xaxes(type='category', categoryorder='category ascending')
                st.plotly_chart(fig1, use_container_width=True)
            with c_master_desc:
                st.info(
                    "**Expirations Used:**\n"
                    "* **VWKS Trend Line:** 7 to 45 DTE\n"
                    "* **Skew Trend Line:** 7 to 60 DTE\n\n"
                    "**What to look for:** A \"Dual Alignment.\" Look for instances where BOTH the yellow line (Skew) and the green line (VWKS) diverge and slope upward concurrently while underlying structural asset prices (White Dotted) remain range-bound.\n\n"
                    "**Why it's useful:** Isolates intense accumulation by cross-checking volume positioning targets against asset options decay pricing patterns directly.")

            # ==========================================
            # 2. VWKS MIGRATION DIVERGENCE (AREA)
            # ==========================================
            st.divider()
            c_vwks, c_vwks_desc = st.columns([2, 1])
            with c_vwks:
                # Map globally smoothed spot and calculate the fully smoothed gap
                agg_vwks['spot_close'] = agg_vwks['date_str'].map(spot_hist)
                agg_vwks['spot_3d_ma'] = agg_vwks['date_str'].map(spot_ma_dict)
                agg_vwks['smooth_gap_pct'] = ((agg_vwks['VWKS_3D_MA'] - agg_vwks['spot_3d_ma']) / agg_vwks[
                    'spot_3d_ma']) * 100

                fig2 = make_subplots(specs=[[{"secondary_y": True}]])
                fig2.add_trace(
                    go.Scatter(x=agg_vwks['date_str'], y=agg_vwks['smooth_gap_pct'], name="Dual-Smoothed % Gap",
                               mode='lines',
                               line=dict(color='#FECB52', width=1.5), fill='tozeroy',
                               fillcolor='rgba(254, 203, 82, 0.15)'), secondary_y=True)
                fig2.add_trace(
                    go.Scatter(x=agg_vwks['date_str'], y=agg_vwks['VWKS'], name="Raw Call VWKS ($)", mode='lines',
                               line=dict(color='rgba(0, 204, 150, 0.4)', width=1)), secondary_y=False)
                fig2.add_trace(go.Scatter(x=agg_vwks['date_str'], y=agg_vwks['VWKS_3D_MA'], name="3-Day MA VWKS ($)",
                                          mode='lines+markers', line=dict(color='#00CC96', width=3)), secondary_y=False)
                fig2.add_trace(go.Scatter(x=spot_hist.index, y=spot_hist.values, name="Spot Price ($)", mode='lines',
                                          line=dict(color='white', width=2, dash='dot')), secondary_y=False)

                fig2.update_layout(title="2. VWKS Migration Divergence (Absolute Strike vs Spot)",
                                   template='plotly_dark',
                                   height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified')
                fig2.update_xaxes(type='category', categoryorder='category ascending')
                fig2.update_yaxes(title_text="Price ($)", secondary_y=False)
                fig2.update_yaxes(title_text="Gap Scale (%)", secondary_y=True, showgrid=False)
                st.plotly_chart(fig2, use_container_width=True)
            with c_vwks_desc:
                st.info("**Expirations Used:** 7 to 45 DTE.\n\n"
                        "**What to look for:** The yellow background mountain range expanding (Rubber Band Stretching), followed by it condensing (Rubber Band Snapping).\n\n"
                        "**Why it's useful:** A widening yellow area shows institutions are aggressively migrating their volume to higher strikes. By smoothing BOTH the spot price and the VWKS, we eliminate daily noise and reveal the true structural tension.")

            # ==========================================
            # 3. ELASTIC BAND OSCILLATOR (NEW SCATTER)
            # ==========================================
            st.divider()
            c_scat, c_scat_desc = st.columns([2, 1])
            with c_scat:
                fig3 = make_subplots(specs=[[{"secondary_y": True}]])

                # The Scatter Plot for the Gap
                fig3.add_trace(go.Scatter(x=agg_vwks['date_str'], y=agg_vwks['smooth_gap_pct'], mode='markers',
                                          name='Smoothed % Gap', marker=dict(color='#FECB52', size=8, opacity=0.8)),
                               secondary_y=False)
                # The Spot Price Line
                fig3.add_trace(go.Scatter(x=spot_hist.index, y=spot_hist.values, name="Spot Price", mode='lines',
                                          line=dict(color='white', width=2)), secondary_y=True)

                # The Static 90-Day Percentile Lines
                fig3.add_hline(y=gap_80th, line_dash="dash", line_color="rgba(239, 85, 59, 0.8)",
                               annotation_text="80th %ile (Extreme Stretch)", secondary_y=False)
                fig3.add_hline(y=gap_20th, line_dash="dash", line_color="rgba(0, 204, 150, 0.8)",
                               annotation_text="20th %ile (Tension Released)", secondary_y=False)

                fig3.update_layout(title="3. VWKS Elastic Band Oscillator (90-Day Percentile Rank)",
                                   template='plotly_dark',
                                   height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified')
                fig3.update_xaxes(type='category', categoryorder='category ascending')
                fig3.update_yaxes(title_text="Dual-Smoothed Gap (%)", secondary_y=False)
                fig3.update_yaxes(title_text="Spot Price ($)", showgrid=False, secondary_y=True)
                st.plotly_chart(fig3, use_container_width=True)
            with c_scat_desc:
                st.info("**Expirations Used:** 7 to 45 DTE.\n\n"
                        "**What to look for:** The yellow dots hitting the red dashed line (80th Percentile) while the white line (Spot Price) is flat or dipping.\n\n"
                        "**Why it's useful:** The flat lines represent the highest and lowest 20% of gaps over the trailing 90 days. When the scatter dots hit the red line, the 'Elastic Band' is maximally stretched relative to recent history, highly increasing the probability of a spot rally to close the gap.")

            # ==========================================
            # 4. FORWARD SKEW INVERSION
            # ==========================================
            st.divider()
            c_skew, c_skew_desc = st.columns([2, 1])
            with c_skew:
                fig4 = make_subplots(specs=[[{"secondary_y": True}]])
                fig4.add_trace(
                    go.Scatter(x=skew_spread['date_str'], y=skew_spread['Skew'], fill='tozeroy', mode='lines',
                               line=dict(color='rgba(0, 204, 150, 0.3)', width=1),
                               fillcolor='rgba(0, 204, 150, 0.1)', name='Raw Daily Skew'), secondary_y=False)
                fig4.add_trace(go.Scatter(x=skew_spread['date_str'], y=skew_spread['Skew_3D_MA'], mode='lines+markers',
                                          line=dict(color='#00CC96', width=3), name='3-Day MA Skew'), secondary_y=False)
                fig4.add_trace(go.Scatter(x=spot_hist.index, y=spot_hist.values, name="Spot Price", mode='lines',
                                          line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig4.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5, secondary_y=False)
                fig4.update_layout(title="4. Forward Skew Inversion (Call IV - Put IV)", template='plotly_dark',
                                   height=350,
                                   margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified')
                fig4.update_xaxes(type='category', categoryorder='category ascending')
                fig4.update_yaxes(title_text="Spread Difference (%)", secondary_y=False)
                fig4.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig4, use_container_width=True)
            with c_skew_desc:
                st.info("**Expirations Used:** 7 to 60 DTE.\n\n"
                        "**What to look for:** The solid green line breaking and holding above the zero line threshold while underlying spot price remains structurally unchanged.\n\n"
                        "**Why it's useful:** Indicates a systematic trend shift wherein institutions pay higher proportional premiums for upside calls relative to downside protection.")

            # ==========================================
            # 5. FAR-OTM (<10Δ) DELTA EXPANSION
            # ==========================================
            st.divider()
            c_wings, c_wings_desc = st.columns([2, 1])
            with c_wings:
                far_otm = t_hist[(t_hist['side'] == 'CALL') & (t_hist['delta'] > 0) & (t_hist['delta'] <= 0.10) & (
                            t_hist['dte'] > 2)].copy()
                far_otm['notional_delta'] = far_otm['delta'] * far_otm['open_interest'] * 100 * far_otm[
                    'underlying_price']
                agg_far = far_otm.groupby('date_str')['notional_delta'].sum().reset_index()
                agg_far['Delta_3D_MA'] = agg_far['notional_delta'].rolling(window=3, min_periods=1).mean()

                fig5 = make_subplots(specs=[[{"secondary_y": True}]])
                fig5.add_trace(
                    go.Bar(x=agg_far['date_str'], y=agg_far['notional_delta'], marker_color='rgba(254, 203, 82, 0.3)',
                           name='Raw <10Δ Notional Delta'), secondary_y=False)
                fig5.add_trace(go.Scatter(x=agg_far['date_str'], y=agg_far['Delta_3D_MA'], mode='lines',
                                          line=dict(color='#FECB52', width=2.5), name='3-Day MA Trend'),
                               secondary_y=False)
                fig5.add_trace(go.Scatter(x=spot_hist.index, y=spot_hist.values, name="Spot Price", mode='lines',
                                          line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig5.update_layout(title="4. Far-OTM (<10Δ) Call Delta Expansion", template='plotly_dark', height=350,
                                   margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified')
                fig5.update_xaxes(type='category', categoryorder='category ascending')
                fig5.update_yaxes(title_text="Notional Delta ($)", secondary_y=False)
                fig5.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig5, use_container_width=True)
            with c_wings_desc:
                st.info("**Expirations Used:** > 2 DTE.\n\n"
                        "**What to look for:** The solid yellow line (3-Day MA) carving out a new structural upward trend, or individual transparent bars spiking massively *above* the trend line.\n\n"
                        "**Why it's useful:** The transparent bars show daily outlier spikes, but the solid trend line reveals when institutions are structurally anchoring a multi-day accumulation phase. Filtering out 0-2 DTE removes intra-day gambling noise, leaving pure swing conviction.")

            # ==========================================
            # 6. TERM STRUCTURE BACKWARDATION FLIP
            # ==========================================
            st.divider()
            c_term, c_term_desc = st.columns([2, 1])
            with c_term:
                atm_calls = t_hist[(t_hist['side'] == 'CALL') & (t_hist['iv'] > 0) & (t_hist['iv'] < 2.0)].copy()
                fm_df = atm_calls[atm_calls['dte'].between(7, 45)]
                bm_df = atm_calls[atm_calls['dte'] > 45]

                if not fm_df.empty:
                    idx_fm = fm_df.groupby(['date_str', 'expiration'])['strike_dist'].idxmin()
                    iv_fm = fm_df.loc[idx_fm].groupby('date_str')['iv'].mean() * 100
                else:
                    iv_fm = pd.Series(dtype=float)

                if not bm_df.empty:
                    idx_bm = bm_df.groupby(['date_str', 'expiration'])['strike_dist'].idxmin()
                    iv_bm = bm_df.loc[idx_bm].groupby('date_str')['iv'].mean() * 100
                else:
                    iv_bm = pd.Series(dtype=float)

                fig6 = make_subplots(specs=[[{"secondary_y": True}]])
                if not iv_fm.empty: fig6.add_trace(
                    go.Scatter(x=iv_fm.index, y=iv_fm.values, name="Front-Month (7-45) IV", mode='lines+markers',
                               line=dict(color='#00CC96', width=3)), secondary_y=False)
                if not iv_bm.empty: fig6.add_trace(
                    go.Scatter(x=iv_bm.index, y=iv_bm.values, name="Back-Month (45+) IV", mode='lines',
                               line=dict(color='#EF553B', width=2)), secondary_y=False)
                fig6.add_trace(go.Scatter(x=spot_hist.index, y=spot_hist.values, name="Spot Price", mode='lines',
                                          line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig6.update_layout(title="6. Term Structure Flip (Backwardation)", template='plotly_dark', height=350,
                                   margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified')
                fig6.update_xaxes(type='category', categoryorder='category ascending')
                fig6.update_yaxes(title_text="Implied Volatility (%)", secondary_y=False)
                fig6.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig6, use_container_width=True)
            with c_term_desc:
                st.info("**Expirations Used:** Front (7-45 DTE) vs. Back (45+ DTE).\n\n"
                        "**What to look for:** Front-month curve spikes cross over and invert above the longer-term baseline blocks.\n\n"
                        "**Why it's useful:** Spotlights short-term premium inflation anomalies that reflect sudden, aggressive localized capital execution.")

# ==========================================
# TAB 5: SIGNALS TESTING
# ==========================================
if active_tab == "🎯 Signals Testing":
    st.header("5D MA Trend & Option Flow Gap Divergence (Signals Testing)")

# ==========================================
# TAB 7.5: BACKTESTED SIGNALS — FILTERED & RISK-MANAGED
# ==========================================
if active_tab == "🎯 Signals Testing":
    st.header("🎯 Backtested Signal Fire Monitor")
    st.markdown("Real-time signal detection using V2 backtest methodology — M3_p90_w90, Put VWKS, Backwardation magnitude, and OTM Delta. **Q1-filtered with -2% stop loss for tradeable quality.**")

    # Date slider for signals
    sig_dates = sorted(ticker_chain['date_str'].unique())
    if len(sig_dates) == 0:
        st.warning("No historical data available.")
    else:
        sig_start = sig_dates[-60] if len(sig_dates) >= 60 else sig_dates[0]
        sig_end = sig_dates[-1]
        sig_start_date, sig_end_date = st.select_slider(
            "Signal Detection Window:",
            options=sig_dates,
            value=(sig_start, sig_end)
        )

        s_hist = ticker_chain[(ticker_chain['date_str'] >= sig_start_date) & (ticker_chain['date_str'] <= sig_end_date)].copy()

        if s_hist.empty:
            st.warning("Insufficient data in selected window.")
        else:
            s_hist['strike_dist'] = (s_hist['strike'] - s_hist['underlying_price']).abs()
            s_spot = s_hist.groupby('date_str')['underlying_price'].first()

            # --- GLOBAL PERCENTILE (90-day window, 90th percentile) ---
            all_dates_full = sorted(ticker_chain['date_str'].unique())
            past_dates_sig = [d for d in all_dates_full if d <= sig_end_date]
            dates_90_sig = past_dates_sig[-90:] if len(past_dates_sig) >= 90 else past_dates_sig

            df_90_sig = ticker_chain[(ticker_chain['date_str'].isin(dates_90_sig)) & (ticker_chain['side'] == 'CALL') & (ticker_chain['dte'].between(7, 45))].copy()
            df_90_sig['vwks_num'] = df_90_sig['strike'] * df_90_sig['volume']
            vwks_90_sig = df_90_sig.groupby('date_str').apply(lambda x: (x['vwks_num'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename('VWKS').reset_index()
            # Global spot smoothing for percentile calc
            global_spot_sig = ticker_chain.groupby('date_str')['underlying_price'].first().reset_index()
            global_spot_sig['Spot_3D_MA'] = global_spot_sig['underlying_price'].rolling(window=3, min_periods=1).mean()
            spot_ma_sig = dict(zip(global_spot_sig['date_str'], global_spot_sig['Spot_3D_MA']))
            vwks_90_sig['Spot_3D_MA'] = vwks_90_sig['date_str'].map(spot_ma_sig)
            vwks_90_sig['VWKS_3D_MA'] = vwks_90_sig['VWKS'].rolling(3, min_periods=1).mean()
            vwks_90_sig['gap_pct'] = ((vwks_90_sig['VWKS_3D_MA'] - vwks_90_sig['Spot_3D_MA']) / vwks_90_sig['Spot_3D_MA']) * 100

            gap_p90 = vwks_90_sig['gap_pct'].quantile(0.90)
            gap_p80 = vwks_90_sig['gap_pct'].quantile(0.80)
            gap_p20 = vwks_90_sig['gap_pct'].quantile(0.20)

            # --- Compute VWKS Gap within window ---
            df_vwks_sig = s_hist[(s_hist['side'] == 'CALL') & (s_hist['dte'].between(7, 45))].copy()
            df_vwks_sig['vwks_num'] = df_vwks_sig['strike'] * df_vwks_sig['volume']
            agg_vwks_sig = df_vwks_sig.groupby('date_str').apply(lambda x: (x['vwks_num'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename('VWKS').reset_index()
            agg_vwks_sig['VWKS_3D_MA'] = agg_vwks_sig['VWKS'].rolling(3, min_periods=1).mean()
            agg_vwks_sig['VWKS_5D_MA'] = agg_vwks_sig['VWKS'].rolling(5, min_periods=3).mean()
            agg_vwks_sig['spot_3d_ma'] = agg_vwks_sig['date_str'].map(spot_ma_sig)
            agg_vwks_sig['smooth_gap_pct'] = ((agg_vwks_sig['VWKS_3D_MA'] - agg_vwks_sig['spot_3d_ma']) / agg_vwks_sig['spot_3d_ma']) * 100

            # --- Compute Put VWKS ---
            df_put_sig = s_hist[(s_hist['side'] == 'PUT') & (s_hist['dte'].between(7, 45))].copy()
            df_put_sig['vwks_num_put'] = df_put_sig['strike'] * df_put_sig['volume']
            agg_put_sig = df_put_sig.groupby('date_str').apply(lambda x: (x['vwks_num_put'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename('VWKS_PUT').reset_index()
            agg_put_sig['VWKS_PUT_3D'] = agg_put_sig['VWKS_PUT'].rolling(3, min_periods=1).mean()
            agg_put_sig['VWKS_PUT_5D'] = agg_put_sig['VWKS_PUT'].rolling(5, min_periods=3).mean()

            # --- Compute Skew ---
            df_skew_sig = s_hist[(s_hist['dte'].between(7, 60)) & (s_hist['iv'] > 0) & (s_hist['iv'] < 2.0)]
            calls_25_sig = df_skew_sig[(df_skew_sig['side'] == 'CALL') & (df_skew_sig['delta'].between(0.2, 0.3))].groupby('date_str')['iv'].mean()
            puts_25_sig = df_skew_sig[(df_skew_sig['side'] == 'PUT') & (df_skew_sig['delta'].between(-0.3, -0.2))].groupby('date_str')['iv'].mean()
            skew_sig = ((calls_25_sig - puts_25_sig) * 100).rename("Skew").reset_index()
            skew_sig['Skew_3D_MA'] = skew_sig['Skew'].rolling(3, min_periods=1).mean()

            # --- Compute OTM Delta (CALLS + PUTS) with expiration week breakdown ---
            far_call_sig = s_hist[(s_hist['side'] == 'CALL') & (s_hist['delta'] > 0) & (s_hist['delta'] <= 0.10) & (s_hist['dte'] > 2)].copy()
            far_put_sig = s_hist[(s_hist['side'] == 'PUT') & (s_hist['delta'] < 0) & (s_hist['delta'] >= -0.10) & (s_hist['dte'] > 2)].copy()

            agg_call_sig = pd.DataFrame(columns=['date_str','notional_delta','Delta_3D_MA'])
            agg_put_sig_otm = pd.DataFrame(columns=['date_str','notional_delta','Delta_3D_MA'])
            agg_net_sig = pd.DataFrame(columns=['date_str','net_delta','Net_3D_MA'])
            call_dte_pivot = pd.DataFrame()
            put_dte_pivot = pd.DataFrame()
            net_dte_pivot = pd.DataFrame()

            if not far_call_sig.empty:
                far_call_sig['notional_delta'] = far_call_sig['delta'] * far_call_sig['open_interest'] * 100 * far_call_sig['underlying_price']
                far_call_sig['dte_bucket'] = far_call_sig['dte'].apply(lambda d: '2-7 DTE' if d<=7 else ('8-15 DTE' if d<=15 else ('16-30 DTE' if d<=30 else ('31-45 DTE' if d<=45 else '46+ DTE'))))
                agg_call_sig = far_call_sig.groupby('date_str')['notional_delta'].sum().reset_index()
                agg_call_sig['Delta_3D_MA'] = agg_call_sig['notional_delta'].rolling(3, min_periods=1).mean()
                # Pivot: date x expiration week
                call_dte_pivot = far_call_sig.groupby(['date_str','dte_bucket'])['notional_delta'].sum().unstack(fill_value=0)

            if not far_put_sig.empty:
                far_put_sig['notional_delta'] = far_put_sig['delta'].abs() * far_put_sig['open_interest'] * 100 * far_put_sig['underlying_price']
                far_put_sig['dte_bucket'] = far_put_sig['dte'].apply(lambda d: '2-7 DTE' if d<=7 else ('8-15 DTE' if d<=15 else ('16-30 DTE' if d<=30 else ('31-45 DTE' if d<=45 else '46+ DTE'))))
                agg_put_sig_otm = far_put_sig.groupby('date_str')['notional_delta'].sum().reset_index()
                agg_put_sig_otm['Delta_3D_MA'] = agg_put_sig_otm['notional_delta'].rolling(3, min_periods=1).mean()
                put_dte_pivot = far_put_sig.groupby(['date_str','dte_bucket'])['notional_delta'].sum().unstack(fill_value=0)

            # Fixed DTE bucket order (short-term -> long-term)
            dte_buckets_order = ['2-7 DTE','8-15 DTE','16-30 DTE','31-45 DTE','46+ DTE']
            dte_colors = ['#EF553B','#FFA15A','#FECB52','#00CC96','#636EFA']

            # Volume-based pivots (same DTE buckets, using raw volume instead of notional delta)
            call_vol_pivot = far_call_sig.groupby(['date_str','dte_bucket'])['volume'].sum().unstack(fill_value=0) if 'dte_bucket' in far_call_sig.columns else pd.DataFrame()
            put_vol_pivot = far_put_sig.groupby(['date_str','dte_bucket'])['volume'].sum().unstack(fill_value=0) if 'dte_bucket' in far_put_sig.columns else pd.DataFrame()

            # OI-based pivots
            call_oi_pivot = far_call_sig.groupby(['date_str','dte_bucket'])['open_interest'].sum().unstack(fill_value=0) if 'dte_bucket' in far_call_sig.columns else pd.DataFrame()
            put_oi_pivot = far_put_sig.groupby(['date_str','dte_bucket'])['open_interest'].sum().unstack(fill_value=0) if 'dte_bucket' in far_put_sig.columns else pd.DataFrame()

            # Net notional delta (calls - puts) total + per DTE bucket
            if not far_call_sig.empty or not far_put_sig.empty:
                # Total net
                net = agg_call_sig[['date_str','notional_delta']].rename(columns={'notional_delta':'call_delta'}).merge(
                    agg_put_sig_otm[['date_str','notional_delta']].rename(columns={'notional_delta':'put_delta'}),
                    on='date_str', how='outer').fillna(0).sort_values('date_str')
                net['net_delta'] = net['call_delta'] - net['put_delta']
                net['Net_3D_MA'] = net['net_delta'].rolling(5, min_periods=2).mean()
                net['nd_rising'] = net['Net_3D_MA'] > net['Net_3D_MA'].shift(1)
                agg_net_sig = net
                # Net per DTE bucket
                if not call_dte_pivot.empty or not put_dte_pivot.empty:
                    c_align = call_dte_pivot.reindex(columns=dte_buckets_order, fill_value=0) if not call_dte_pivot.empty else pd.DataFrame(0, index=put_dte_pivot.index, columns=dte_buckets_order)
                    p_align = put_dte_pivot.reindex(columns=dte_buckets_order, fill_value=0) if not put_dte_pivot.empty else pd.DataFrame(0, index=call_dte_pivot.index, columns=dte_buckets_order)
                    net_dte_pivot = c_align - p_align
                    net_dte_pivot = net_dte_pivot.reindex(sorted(net_dte_pivot.index), fill_value=0)

            # For backward compat with M5 signal detection
            agg_far_sig = agg_call_sig.copy()
            if not agg_far_sig.empty:
                agg_far_sig['nd_rising'] = agg_far_sig['Delta_3D_MA'] > agg_far_sig['Delta_3D_MA'].shift(1)
            else:
                agg_far_sig = pd.DataFrame(columns=['date_str','notional_delta','Delta_3D_MA','nd_rising'])

            # --- Compute Backwardation ---
            atm_calls_sig = s_hist[(s_hist['side'] == 'CALL') & (s_hist['iv'] > 0) & (s_hist['iv'] < 2.0)].copy()
            fm_atm_sig = atm_calls_sig[atm_calls_sig['dte'].between(7, 45)]
            bm_atm_sig = atm_calls_sig[atm_calls_sig['dte'] > 45]
            iv_fm_series = pd.Series(dtype=float)
            iv_bm_series = pd.Series(dtype=float)
            if not fm_atm_sig.empty:
                idx_fm_s = fm_atm_sig.groupby(['date_str', 'expiration'])['strike_dist'].idxmin()
                iv_fm_series = fm_atm_sig.loc[idx_fm_s].groupby('date_str')['iv'].mean() * 100
            if not bm_atm_sig.empty:
                idx_bm_s = bm_atm_sig.groupby(['date_str', 'expiration'])['strike_dist'].idxmin()
                iv_bm_series = bm_atm_sig.loc[idx_bm_s].groupby('date_str')['iv'].mean() * 100

            # --- DETECT SIGNALS ---
            # M3_p90_w90: gap > 90th percentile AND spot not spiked (5d < 5%)
            agg_vwks_sig['gap_rising'] = agg_vwks_sig['smooth_gap_pct'] > agg_vwks_sig['smooth_gap_pct'].shift(1)
            agg_vwks_sig['vwks_rising'] = agg_vwks_sig['VWKS_3D_MA'] > agg_vwks_sig['VWKS_3D_MA'].shift(1)
            # Spot 5d change proxy
            spot_series = s_hist.groupby('date_str')['underlying_price'].first()
            spot_5d_chg = spot_series.pct_change(5).abs()
            spot_not_spiked = spot_5d_chg < 0.05

            # M3 signal
            sig_m3 = (agg_vwks_sig['smooth_gap_pct'] > gap_p90) & agg_vwks_sig['date_str'].map(spot_not_spiked).fillna(False)
            sig_m3_dates = set(agg_vwks_sig.loc[sig_m3.values, 'date_str']) if sig_m3.any() else set()

            # Q1 filter: gap < 6.35% (backtest-derived threshold across 61 tickers)
            q1_threshold = 6.35
            sig_m3_q1 = sig_m3 & (agg_vwks_sig['smooth_gap_pct'] < q1_threshold)
            sig_m3_q1_dates = set(agg_vwks_sig.loc[sig_m3_q1.values, 'date_str']) if sig_m3_q1.any() else set()

            # M7: Call VWKS rising + Put VWKS falling
            if not agg_put_sig.empty and not agg_vwks_sig.empty:
                merged_vwks = agg_vwks_sig[['date_str','vwks_rising']].merge(agg_put_sig[['date_str','VWKS_PUT_3D']], on='date_str', how='outer').sort_values('date_str')
                merged_vwks['put_falling'] = merged_vwks['VWKS_PUT_3D'] < merged_vwks['VWKS_PUT_3D'].shift(1)
                sig_m7 = merged_vwks['vwks_rising'] & merged_vwks['put_falling'] & merged_vwks['date_str'].map(spot_not_spiked).fillna(False)
                sig_m7_dates = set(merged_vwks.loc[sig_m7.values, 'date_str']) if sig_m7.any() else set()
            else:
                sig_m7_dates = set()

            # M5: OTM Delta rising
            if not agg_far_sig.empty:
                sig_m5 = agg_far_sig['nd_rising'] & agg_far_sig['date_str'].map(spot_not_spiked).fillna(False)
                sig_m5_dates = set(agg_far_sig.loc[sig_m5.values, 'date_str']) if sig_m5.any() else set()
            else:
                sig_m5_dates = set()

            # BW >= 2%
            if not iv_fm_series.empty and not iv_bm_series.empty:
                bw_df = pd.DataFrame({'fm': iv_fm_series, 'bm': iv_bm_series}).fillna(0)
                bw_df['bw_mag'] = bw_df['fm'] - bw_df['bm']
                bw_df['bw_2pct'] = bw_df['bw_mag'] >= 2.0
                sig_bw2_dates = set(bw_df[bw_df['bw_2pct']].index) if bw_df['bw_2pct'].any() else set()
            else:
                sig_bw2_dates = set()

            # --- CURRENT STATUS PANEL ---
            latest_date = sig_dates[-1]
            st.divider()
            st.subheader("📡 Current Signal Status")
            col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)

            # Get latest values
            latest_gap = agg_vwks_sig[agg_vwks_sig['date_str'] == latest_date]['smooth_gap_pct'].values
            latest_gap_val = latest_gap[0] if len(latest_gap) > 0 else 0
            gap_percentile = (vwks_90_sig['gap_pct'] < latest_gap_val).mean() * 100 if len(vwks_90_sig) > 0 else 0

            m3_firing = latest_date in sig_m3_dates
            m3_q1_firing = latest_date in sig_m3_q1_dates
            m7_firing = latest_date in sig_m7_dates
            m5_firing = latest_date in sig_m5_dates
            bw2_firing = latest_date in sig_bw2_dates

            with col_s1:
                st.metric("Gap vs 90%ile", f"{latest_gap_val:.1f}%", f"{latest_gap_val - gap_p90:+.1f}%")
            with col_s2:
                status_m3 = "🟢 FIRING" if m3_firing else "⚫ Silent"
                st.metric("M3 (Elastic Band)", status_m3, "Q1 Qualified" if m3_q1_firing else ("Q2-4" if m3_firing else None))
            with col_s3:
                status_m7 = "🟢 FIRING" if m7_firing else "⚫ Silent"
                st.metric("M7 (Call+Put VWKS)", status_m7)
            with col_s4:
                status_m5 = "🟢 FIRING" if m5_firing else "⚫ Silent"
                st.metric("M5 (OTM Delta)", status_m5)
            with col_s5:
                status_bw = "🟢 FIRING" if bw2_firing else "⚫ Silent"
                st.metric("BW >= 2%", status_bw)

            # Confluence indicator
            active_count = sum([m3_q1_firing, m7_firing, m5_firing, bw2_firing])
            if active_count >= 3:
                st.success(f"🔥 HIGH CONVICTION: {active_count}/4 signals active — M3 Q1({m3_q1_firing}) + M7({m7_firing}) + M5({m5_firing}) + BW2%({bw2_firing})")
            elif active_count >= 2:
                st.warning(f"⚡ MODERATE: {active_count}/4 signals active")
            elif m3_q1_firing:
                st.info(f"✅ M3 Q1 firing — 83% historical hit rate at t7 (with -2% stop). Tradeable.")

            # ==========================================
            # CHART 1: M3 ELASTIC BAND OSCILLATOR (90th %ile)
            # ==========================================
            st.divider()
            st.subheader("1. M3 Elastic Band — 90th Percentile Signals")
            c_m3, c_m3_desc = st.columns([2.5, 1])
            with c_m3:
                fig_s1 = make_subplots(specs=[[{"secondary_y": True}]])

                # Gap scatter
                fig_s1.add_trace(go.Scatter(x=agg_vwks_sig['date_str'], y=agg_vwks_sig['smooth_gap_pct'],
                    mode='markers', name='Gap %', marker=dict(color='#FECB52', size=6, opacity=0.7)), secondary_y=False)

                # 90th percentile line
                fig_s1.add_hline(y=gap_p90, line_dash="dash", line_color="rgba(239, 85, 59, 0.9)",
                    annotation_text=f"90th %ile ({gap_p90:.1f}%)", secondary_y=False)
                # 80th percentile line (for reference)
                fig_s1.add_hline(y=gap_p80, line_dash="dot", line_color="rgba(254, 203, 82, 0.5)",
                    annotation_text=f"80th %ile", secondary_y=False)

                # Q1 threshold line
                fig_s1.add_hline(y=q1_threshold, line_dash="dashdot", line_color="rgba(0, 204, 150, 0.7)",
                    annotation_text=f"Q1 Filter ({q1_threshold:.1f}%)", secondary_y=False)

                # Signal markers — M3 fires (red outline for Q2-4, green for Q1)
                if sig_m3.any():
                    m3_fire = agg_vwks_sig[sig_m3.values]
                    m3_q1_fire = agg_vwks_sig[sig_m3_q1.values]
                    m3_q234_fire = agg_vwks_sig[sig_m3.values & ~sig_m3_q1.values]

                    if len(m3_q1_fire) > 0:
                        fig_s1.add_trace(go.Scatter(x=m3_q1_fire['date_str'], y=m3_q1_fire['smooth_gap_pct'],
                            mode='markers', name='M3 Q1 Signal (TRADE)',
                            marker=dict(color='#00CC96', size=14, symbol='star', line=dict(color='white', width=1))),
                            secondary_y=False)
                    if len(m3_q234_fire) > 0:
                        fig_s1.add_trace(go.Scatter(x=m3_q234_fire['date_str'], y=m3_q234_fire['smooth_gap_pct'],
                            mode='markers', name='M3 Q2-4 Signal (FILTERED)',
                            marker=dict(color='#EF553B', size=10, symbol='x', line=dict(color='white', width=1))),
                            secondary_y=False)

                # Spot price overlay
                fig_s1.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s1.update_layout(title="M3 Elastic Band Oscillator — 90th %ile Trigger", template='plotly_dark',
                    height=400, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
                fig_s1.update_xaxes(type='category', categoryorder='category ascending')
                fig_s1.update_yaxes(title_text="Gap (%)", secondary_y=False)
                fig_s1.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s1, use_container_width=True)
            with c_m3_desc:
                st.info("**Backtest Result:** M3_p90_w90 + Q1 filter (gap < " + f"{q1_threshold:.1f}%" + ") + -2% stop = **83% hit rate at t7, -4% max DD.**\n\n"
                    "**Green stars** = Q1 signals (tradeable). **Red X** = Q2-4 signals (filtered — higher gap = lower quality).\n\n"
                    "**90th percentile line:** Gap threshold from 90-day rolling window. When gap crosses above with spot < 5% move = signal.")

            # --- VWKS/SPOT gap highlights (for Charts 2 & 3) ---
            # Yellow background when spot is within 2% of VWKS or has crossed over
            if not agg_vwks_sig.empty and not agg_put_sig.empty and not s_spot.empty:
                # Merge spot with call and put VWKS
                spot_df = s_spot.reset_index(); spot_df.columns = ['date_str','spot']
                gap_hl = agg_vwks_sig[['date_str','VWKS_3D_MA','VWKS_5D_MA']].merge(
                    agg_put_sig[['date_str','VWKS_PUT_3D','VWKS_PUT_5D']], on='date_str', how='inner'
                ).merge(spot_df, on='date_str', how='inner')
                # Call gap % and put gap % for 3D
                gap_hl['call_gap_3d'] = (gap_hl['spot'] - gap_hl['VWKS_3D_MA']) / gap_hl['spot'] * 100
                gap_hl['put_gap_3d'] = (gap_hl['spot'] - gap_hl['VWKS_PUT_3D']) / gap_hl['spot'] * 100
                gap_hl['call_gap_5d'] = (gap_hl['spot'] - gap_hl['VWKS_5D_MA']) / gap_hl['spot'] * 100
                gap_hl['put_gap_5d'] = (gap_hl['spot'] - gap_hl['VWKS_PUT_5D']) / gap_hl['spot'] * 100
                # Highlight: within 1% OR crossed over (call: spot>call VWKS, put: spot<put VWKS)
                gap_hl['call_hl_3d'] = (gap_hl['call_gap_3d'].abs() < 1) | (gap_hl['spot'] > gap_hl['VWKS_3D_MA'])
                gap_hl['put_hl_3d'] = (gap_hl['put_gap_3d'].abs() < 1) | (gap_hl['spot'] < gap_hl['VWKS_PUT_3D'])
                gap_hl['call_hl_5d'] = (gap_hl['call_gap_5d'].abs() < 1) | (gap_hl['spot'] > gap_hl['VWKS_5D_MA'])
                gap_hl['put_hl_5d'] = (gap_hl['put_gap_5d'].abs() < 1) | (gap_hl['spot'] < gap_hl['VWKS_PUT_5D'])
                gap_hl['any_hl_3d'] = gap_hl['call_hl_3d'] | gap_hl['put_hl_3d']
                gap_hl['any_hl_5d'] = gap_hl['call_hl_5d'] | gap_hl['put_hl_5d']
                # Find contiguous blocks of highlighted dates for 3D and 5D
                hl_dates_3d = gap_hl[gap_hl['any_hl_3d']]['date_str'].tolist()
                hl_dates_5d = gap_hl[gap_hl['any_hl_5d']]['date_str'].tolist()
            else:
                hl_dates_3d = []
                hl_dates_5d = []

            # ==========================================
            # CHART 2: PUT VWKS DIVERGENCE (NEW)
            # ==========================================
            st.divider()
            c_put, c_put_desc = st.columns([2, 1])
            with c_put:
                fig_s2 = make_subplots(specs=[[{"secondary_y": True}]])

                # Yellow background bars first (render behind everything)
                all_dates_c2 = sorted(set(agg_vwks_sig['date_str']))
                hl_mask_c2 = [d in hl_dates_3d for d in all_dates_c2]
                y_min_c2 = min(agg_vwks_sig['VWKS_3D_MA'].min(), agg_put_sig['VWKS_PUT_3D'].min()) * 0.98
                y_max_c2 = max(agg_vwks_sig['VWKS_3D_MA'].max(), agg_put_sig['VWKS_PUT_3D'].max()) * 1.02
                fig_s2.add_trace(go.Bar(x=all_dates_c2, y=[y_max_c2]*len(all_dates_c2),
                    base=[y_min_c2]*len(all_dates_c2),
                    marker_color=['rgba(255,255,0,0.18)' if m else 'rgba(0,0,0,0)' for m in hl_mask_c2],
                    marker_line_width=0, showlegend=False, hoverinfo='skip'), secondary_y=False)

                # Call VWKS
                fig_s2.add_trace(go.Scatter(x=agg_vwks_sig['date_str'], y=agg_vwks_sig['VWKS_3D_MA'],
                    name="Call VWKS 3D MA", mode='lines+markers', line=dict(color='#00CC96', width=2.5)), secondary_y=False)
                # Put VWKS
                if not agg_put_sig.empty:
                    fig_s2.add_trace(go.Scatter(x=agg_put_sig['date_str'], y=agg_put_sig['VWKS_PUT_3D'],
                        name="Put VWKS 3D MA (NEW)", mode='lines+markers', line=dict(color='#EF553B', width=2.5)), secondary_y=False)

                # M7 signal markers
                if sig_m7_dates:
                    m7_dates_list = sorted(sig_m7_dates)
                    m7_gaps = agg_vwks_sig[agg_vwks_sig['date_str'].isin(m7_dates_list)]
                    if len(m7_gaps) > 0:
                        fig_s2.add_trace(go.Scatter(x=m7_gaps['date_str'], y=m7_gaps['VWKS_3D_MA'],
                            mode='markers', name='M7 Signal (Call Up + Put Down)',
                            marker=dict(color='#FECB52', size=12, symbol='diamond', line=dict(color='white', width=1))),
                            secondary_y=False)

                # Spot price (same axis as VWKS — all in dollars)
                fig_s2.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=False)

                fig_s2.update_layout(title="2. Put VWKS Divergence — Dual Accumulation Check", template='plotly_dark',
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
                fig_s2.update_xaxes(type='category', categoryorder='category ascending')
                fig_s2.update_yaxes(title_text="Price ($)", secondary_y=False, range=[y_min_c2, y_max_c2])
                st.plotly_chart(fig_s2, use_container_width=True)
            with c_put_desc:
                st.info("**NEW — Backtest Validated:** M7 (Call VWKS up + Put VWKS down) beats M1 by **6% hit rate**.\n\n"
                    "**Green line** = Call VWKS (volume-weighted strike for calls). **Red line** = Put VWKS (for puts).\n\n"
                    "**What to look for:** Green rising while red falling = genuine institutional accumulation. When both rise = hedging, not accumulation (M8 — ignore).\n\n"
                    "**Yellow diamonds** = M7 signal fires (Call up + Put down + spot not spiked). 56% historical hit rate at t10.")

            # ==========================================
            # CHART 3: PUT VWKS DIVERGENCE — 5D MA (Smoother)
            # ==========================================
            st.divider()
            c_put5, c_put5_desc = st.columns([2, 1])
            with c_put5:
                fig_s3 = make_subplots(specs=[[{"secondary_y": False}]])

                # Yellow background bars first (render behind everything)
                all_dates_c3 = sorted(set(agg_vwks_sig['date_str']))
                hl_mask_c3 = [d in hl_dates_5d for d in all_dates_c3]
                y_min_c3 = min(agg_vwks_sig['VWKS_5D_MA'].min(), agg_put_sig['VWKS_PUT_5D'].min()) * 0.98
                y_max_c3 = max(agg_vwks_sig['VWKS_5D_MA'].max(), agg_put_sig['VWKS_PUT_5D'].max()) * 1.02
                fig_s3.add_trace(go.Bar(x=all_dates_c3, y=[y_max_c3]*len(all_dates_c3),
                    base=[y_min_c3]*len(all_dates_c3),
                    marker_color=['rgba(255,255,0,0.18)' if m else 'rgba(0,0,0,0)' for m in hl_mask_c3],
                    marker_line_width=0, showlegend=False, hoverinfo='skip'))

                # Call VWKS 5D MA
                fig_s3.add_trace(go.Scatter(x=agg_vwks_sig['date_str'], y=agg_vwks_sig['VWKS_5D_MA'],
                    name="Call VWKS 5D MA", mode='lines+markers', line=dict(color='#00CC96', width=2.5)))
                # Put VWKS 5D MA
                if not agg_put_sig.empty:
                    fig_s3.add_trace(go.Scatter(x=agg_put_sig['date_str'], y=agg_put_sig['VWKS_PUT_5D'],
                        name="Put VWKS 5D MA", mode='lines+markers', line=dict(color='#EF553B', width=2.5)))

                # M7 signal markers
                if sig_m7_dates:
                    m7_dates_list = sorted(sig_m7_dates)
                    m7_fire5 = agg_vwks_sig[agg_vwks_sig['date_str'].isin(m7_dates_list)]
                    if len(m7_fire5) > 0:
                        fig_s3.add_trace(go.Scatter(x=m7_fire5['date_str'], y=m7_fire5['VWKS_5D_MA'],
                            mode='markers', name='M7 Signal',
                            marker=dict(color='#FECB52', size=12, symbol='diamond', line=dict(color='white', width=1))))

                # Spot price
                fig_s3.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')))

                fig_s3.update_layout(title="3. Put VWKS Divergence — 5-Day MA (Smoother Trend)", template='plotly_dark',
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
                fig_s3.update_xaxes(type='category', categoryorder='category ascending')
                fig_s3.update_yaxes(title_text="Price ($)", range=[y_min_c3, y_max_c3])
                st.plotly_chart(fig_s3, use_container_width=True)
            with c_put5_desc:
                st.info("**Same as Chart 2, but smoothed with 5-day MA instead of 3-day.**\n\n"
                    "Less noise, clearer trend. Green rising + red falling = accumulation. Yellow diamonds = M7 signal.\n\n"
                    "Compare Charts 2 and 3 to see short-term vs medium-term VWKS divergence.")

            # ==========================================
            # CHART 4: BACKWARDATION MAGNITUDE MONITOR
            # ==========================================
            st.divider()
            c_bw, c_bw_desc = st.columns([2, 1])
            with c_bw:
                fig_s3 = make_subplots(specs=[[{"secondary_y": True}]])

                # Front-month IV
                if not iv_fm_series.empty:
                    fig_s3.add_trace(go.Scatter(x=iv_fm_series.index, y=iv_fm_series.values,
                        name="Front-Month IV (7-45 DTE)", mode='lines+markers',
                        line=dict(color='#00CC96', width=3)), secondary_y=False)
                # Back-month IV
                if not iv_bm_series.empty:
                    fig_s3.add_trace(go.Scatter(x=iv_bm_series.index, y=iv_bm_series.values,
                        name="Back-Month IV (45+ DTE)", mode='lines',
                        line=dict(color='#EF553B', width=2)), secondary_y=False)

                # BW magnitude as colored area
                if not iv_fm_series.empty and not iv_bm_series.empty:
                    bw_common = iv_fm_series.index.intersection(iv_bm_series.index)
                    bw_mag_vals = iv_fm_series[bw_common] - iv_bm_series[bw_common]
                    bw_colors = ['rgba(0,204,150,0.3)' if v >= 2 else ('rgba(254,203,82,0.2)' if v >= 0 else 'rgba(239,85,59,0.2)') for v in bw_mag_vals.values]
                    fig_s3.add_trace(go.Bar(x=bw_common, y=bw_mag_vals.values,
                        name='BW Magnitude', marker_color=bw_colors), secondary_y=True)

                    # Tier lines
                    for tier_val, tier_label, tier_color in [(2.0, '2% Tier (Quality Filter)', 'rgba(0,204,150,0.7)'), (1.0, '1%', 'rgba(254,203,82,0.4)')]:
                        fig_s3.add_hline(y=tier_val, line_dash="dash", line_color=tier_color,
                            annotation_text=tier_label, secondary_y=True)

                # BW >= 2% signal markers
                if sig_bw2_dates:
                    bw2_list = sorted(sig_bw2_dates)
                    bw2_ivs = iv_fm_series[bw2_list] if not iv_fm_series.empty else pd.Series()
                    if len(bw2_ivs) > 0:
                        fig_s3.add_trace(go.Scatter(x=bw2_ivs.index, y=bw2_ivs.values,
                            mode='markers', name='BW >= 2% Signal',
                            marker=dict(color='#00CC96', size=10, symbol='triangle-up', line=dict(color='white', width=1))),
                            secondary_y=False)

                # Spot
                fig_s3.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s3.update_layout(title="4. Backwardation Magnitude — Tier Monitor", template='plotly_dark',
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
                fig_s3.update_xaxes(type='category', categoryorder='category ascending')
                fig_s3.update_yaxes(title_text="IV (%)", secondary_y=False)
                fig_s3.update_yaxes(title_text="BW Spread (%)", secondary_y=True, showgrid=False)
                st.plotly_chart(fig_s3, use_container_width=True)
            with c_bw_desc:
                st.info("**Backtest Result:** BW >= 2% is the sweet spot — **60% hit rate standalone**, +2-4% hit rate when layered on other signals.\n\n"
                    "**Green bars** = front IV > back IV by >= 2% (quality filter active). **Yellow** = 0-2%. **Red** = contango (front < back).\n\n"
                    "**Green triangles** = BW >= 2% signals. Higher magnitude (>3-5%) = higher returns but lower hit rate.")

            # ==========================================
            # CHART 5: OTM DELTA — CALLS vs PUTS by Expiration Week (Top 5)
            # ==========================================
            st.divider()
            c_otm, c_otm_desc = st.columns([2, 1])
            with c_otm:
                fig_s4 = make_subplots(specs=[[{"secondary_y": True}]])

                # CALLS stacked by DTE bucket (positive)
                call_plot = call_dte_pivot.reindex(columns=[b for b in dte_buckets_order if b in call_dte_pivot.columns], fill_value=0) if not call_dte_pivot.empty else pd.DataFrame()
                if not call_plot.empty:
                    call_plot = call_plot.reindex(sorted(call_plot.index), fill_value=0)
                    for wi, bucket in enumerate(dte_buckets_order):
                        if bucket in call_plot.columns:
                            vals = call_plot[bucket]
                            if vals.sum() > 0:
                                fig_s4.add_trace(go.Bar(x=call_plot.index, y=vals,
                                    name=f'Call {bucket}', marker_color=dte_colors[wi], showlegend=True), secondary_y=False)

                # PUTS stacked by DTE bucket (negative)
                put_plot = put_dte_pivot.reindex(columns=[b for b in dte_buckets_order if b in put_dte_pivot.columns], fill_value=0) if not put_dte_pivot.empty else pd.DataFrame()
                if not put_plot.empty:
                    put_plot = put_plot.reindex(sorted(put_plot.index), fill_value=0)
                    for wi, bucket in enumerate(dte_buckets_order):
                        if bucket in put_plot.columns:
                            vals = -put_plot[bucket]
                            if abs(vals).sum() > 0:
                                fig_s4.add_trace(go.Bar(x=put_plot.index, y=vals,
                                    name=f'Put {bucket}', marker_color=dte_colors[wi], showlegend=True), secondary_y=False)

                # 3D MA lines for total calls and puts
                if not agg_call_sig.empty:
                    fig_s4.add_trace(go.Scatter(x=agg_call_sig['date_str'], y=agg_call_sig['Delta_3D_MA'],
                        mode='lines', line=dict(color='#00CC96', width=2), name='Calls 3D MA'), secondary_y=False)
                if not agg_put_sig_otm.empty:
                    fig_s4.add_trace(go.Scatter(x=agg_put_sig_otm['date_str'], y=-agg_put_sig_otm['Delta_3D_MA'],
                        mode='lines', line=dict(color='#EF553B', width=2), name='Puts 3D MA'), secondary_y=False)

                # Zero line
                fig_s4.add_hline(y=0, line_color='white', line_width=1.5, opacity=0.5, secondary_y=False)

                # M5 signal markers
                if sig_m5_dates and not agg_call_sig.empty:
                    m5_fire = agg_call_sig[agg_call_sig['date_str'].isin(sig_m5_dates)]
                    if len(m5_fire) > 0:
                        fig_s4.add_trace(go.Scatter(x=m5_fire['date_str'], y=m5_fire['Delta_3D_MA'],
                            mode='markers', name='M5 Signal',
                            marker=dict(color='#FECB52', size=12, symbol='triangle-up', line=dict(color='white', width=1))),
                            secondary_y=False)

                fig_s4.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s4.update_layout(title="4. Far-OTM (<10Δ) Notional Delta — Calls vs Puts by DTE",
                    template='plotly_dark', barmode='relative', bargap=0,
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(size=9)))
                fig_s4.update_xaxes(type='category', categoryorder='category ascending')
                fig_s4.update_yaxes(title_text="Notional Delta ($)", secondary_y=False)
                fig_s4.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s4, use_container_width=True)
            with c_otm_desc:
                st.info("**Calls (above zero) vs Puts (below zero) — stacked by DTE bucket.**\n\n"
                    "Red=2-7d, Orange=8-15d, Yellow=16-30d, Green=31-45d, Blue=46+d. Short-term = more speculative.\n\n"
                    "**Solid lines** = 3D MA for total calls (green) and puts (red). **White line** = zero split. **Yellow triangles** = M5 signal.")

            # ==========================================
            # CHART 6: NET NOTIONAL DELTA by DTE Bucket
            # ==========================================
            st.divider()
            c_net, c_net_desc = st.columns([2, 1])
            with c_net:
                fig_s5 = make_subplots(specs=[[{"secondary_y": True}]])

                net_plot = net_dte_pivot.reindex(columns=[b for b in dte_buckets_order if b in net_dte_pivot.columns], fill_value=0) if not net_dte_pivot.empty else pd.DataFrame()
                if not net_plot.empty:
                    net_plot = net_plot.reindex(sorted(net_plot.index), fill_value=0)
                    for wi, bucket in enumerate(dte_buckets_order):
                        if bucket in net_plot.columns:
                            vals = net_plot[bucket]
                            if abs(vals).sum() > 0:
                                fig_s5.add_trace(go.Bar(x=net_plot.index, y=vals,
                                    name=bucket, marker_color=dte_colors[wi], showlegend=True), secondary_y=False)

                if not agg_net_sig.empty:
                    fig_s5.add_trace(go.Scatter(x=agg_net_sig['date_str'], y=agg_net_sig['Net_3D_MA'],
                        mode='lines', line=dict(color='#00CC96', width=2.5), name='Net 5D MA'), secondary_y=False)
                    fig_s5.add_hline(y=0, line_color='white', line_width=1, opacity=0.4, secondary_y=False)

                fig_s5.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s5.update_layout(title="6. Net Far-OTM Notional Delta (Calls − Puts) by DTE",
                    template='plotly_dark', barmode='relative', bargap=0,
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(size=9)))
                fig_s5.update_xaxes(type='category', categoryorder='category ascending')
                fig_s5.update_yaxes(title_text="Net Notional Delta ($)", secondary_y=False)
                fig_s5.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s5, use_container_width=True)
            with c_net_desc:
                st.info("**Net = Calls minus Puts, stacked by DTE bucket.**\n\n"
                    "Red=2-7d, Orange=8-15d, Yellow=16-30d, Green=31-45d, Blue=46+d.\n\n"
                    "**Green line** = 5-day MA of total net delta. Above zero = net bullish, below = net bearish.")

            # ==========================================
            # CHART 7: NET VOLUME by DTE Bucket
            # ==========================================
            st.divider()
            c_vol, c_vol_desc = st.columns([2, 1])
            with c_vol:
                fig_s6 = make_subplots(specs=[[{"secondary_y": True}]])

                # Net volume pivot
                vol_net_pivot = pd.DataFrame()
                if not call_vol_pivot.empty or not put_vol_pivot.empty:
                    cv = call_vol_pivot.reindex(columns=[b for b in dte_buckets_order if b in call_vol_pivot.columns], fill_value=0) if not call_vol_pivot.empty else pd.DataFrame(0, index=put_vol_pivot.index, columns=[b for b in dte_buckets_order if b in put_vol_pivot.columns])
                    pv = put_vol_pivot.reindex(columns=[b for b in dte_buckets_order if b in put_vol_pivot.columns], fill_value=0) if not put_vol_pivot.empty else pd.DataFrame(0, index=call_vol_pivot.index, columns=[b for b in dte_buckets_order if b in call_vol_pivot.columns])
                    vol_net_pivot = cv - pv
                    vol_net_pivot = vol_net_pivot.reindex(sorted(vol_net_pivot.index), fill_value=0)

                if not vol_net_pivot.empty:
                    for wi, bucket in enumerate(dte_buckets_order):
                        if bucket in vol_net_pivot.columns:
                            vals = vol_net_pivot[bucket]
                            if abs(vals).sum() > 0:
                                fig_s6.add_trace(go.Bar(x=vol_net_pivot.index, y=vals,
                                    name=bucket, marker_color=dte_colors[wi], showlegend=True), secondary_y=False)

                # 5D MA of total net volume
                if not vol_net_pivot.empty:
                    total_vol = vol_net_pivot.sum(axis=1)
                    vol_5d = total_vol.rolling(5, min_periods=2).mean()
                    fig_s6.add_trace(go.Scatter(x=total_vol.index, y=vol_5d,
                        mode='lines', line=dict(color='#00CC96', width=2.5), name='Volume 5D MA'), secondary_y=False)
                    fig_s6.add_hline(y=0, line_color='white', line_width=1, opacity=0.4, secondary_y=False)

                fig_s6.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s6.update_layout(title="7. Net Far-OTM Volume (Calls − Puts) by DTE",
                    template='plotly_dark', barmode='relative', bargap=0,
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(size=9)))
                fig_s6.update_xaxes(type='category', categoryorder='category ascending')
                fig_s6.update_yaxes(title_text="Net Volume", secondary_y=False)
                fig_s6.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s6, use_container_width=True)
            with c_vol_desc:
                st.info("**Net Volume = Call volume minus Put volume for far-OTM options, stacked by DTE.**\n\n"
                    "Unlike notional delta, volume is not inflated by time premium — it's a cleaner measure of raw activity.\n\n"
                    "**Green line** = 5-day MA. Above zero = more call volume (speculation), below = more put volume (hedging).")






# ==========================================
# TAB 6: SIGNALS
# ==========================================
if active_tab == "⚡ Signals":
    st.header("⚡ Signals")
    
    sig_dates_t6 = sorted(ticker_chain['date_str'].dropna().unique())
    if len(sig_dates_t6) == 0:
        st.warning("No historical data available.")
        st.stop()
        
    sig_start_t6 = sig_dates_t6[-60] if len(sig_dates_t6) >= 60 else sig_dates_t6[0]
    sig_end_t6 = sig_dates_t6[-1]
    sig_start_date_t6, sig_end_date_t6 = st.select_slider(
        "Signal Detection Window:",
        options=sig_dates_t6,
        value=(sig_start_t6, sig_end_t6),
        key="sig_tab_6_slider"
    )
    
    # --- INDEPENDENT DATA PREP FOR TAB 6 ---
    s_hist = ticker_chain[(ticker_chain['date_str'] >= sig_start_date_t6) & (ticker_chain['date_str'] <= sig_end_date_t6)].copy()
    s_spot = s_hist.groupby('date_str')['underlying_price'].first()
    spot_df = s_spot.reset_index(); spot_df.columns = ['date_str','spot']
    
    df_vwks = s_hist[(s_hist['side'] == 'CALL') & (s_hist['dte'].between(7, 45))].copy()
    df_vwks['vwks_num'] = df_vwks['strike'] * df_vwks['volume']
    agg_vwks_sig = df_vwks.groupby('date_str').apply(lambda x: (x['vwks_num'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename('VWKS').reset_index()
    agg_vwks_sig['VWKS_3D_MA'] = agg_vwks_sig['VWKS'].rolling(3, min_periods=1).mean()
    agg_vwks_sig['VWKS_5D_MA'] = agg_vwks_sig['VWKS'].rolling(5, min_periods=3).mean()
    
    df_put = s_hist[(s_hist['side'] == 'PUT') & (s_hist['dte'].between(7, 45))].copy()
    df_put['vwks_num_put'] = df_put['strike'] * df_put['volume']
    agg_put_sig = df_put.groupby('date_str').apply(lambda x: (x['vwks_num_put'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename('VWKS_PUT').reset_index()
    agg_put_sig['VWKS_PUT_3D'] = agg_put_sig['VWKS_PUT'].rolling(3, min_periods=1).mean()
    agg_put_sig['VWKS_PUT_5D'] = agg_put_sig['VWKS_PUT'].rolling(5, min_periods=3).mean()
    
    gap_hl = agg_vwks_sig[['date_str','VWKS_3D_MA','VWKS_5D_MA']].merge(agg_put_sig[['date_str','VWKS_PUT_3D','VWKS_PUT_5D']], on='date_str', how='inner').merge(spot_df, on='date_str', how='inner')
    gap_hl['call_gap_5d'] = (gap_hl['spot'] - gap_hl['VWKS_5D_MA']) / gap_hl['spot'] * 100
    gap_hl['call_hl_5d'] = (gap_hl['call_gap_5d'].abs() < 1) | (gap_hl['spot'] > gap_hl['VWKS_5D_MA'])
    gap_hl['put_gap_5d'] = (gap_hl['spot'] - gap_hl['VWKS_PUT_5D']) / gap_hl['spot'] * 100
    gap_hl['put_hl_5d'] = (gap_hl['put_gap_5d'].abs() < 1) | (gap_hl['spot'] < gap_hl['VWKS_PUT_5D'])
    
    far_call = s_hist[(s_hist['side'] == 'CALL') & (s_hist['delta'] > 0) & (s_hist['delta'] <= 0.10) & (s_hist['dte'] > 2)].copy()
    far_put = s_hist[(s_hist['side'] == 'PUT') & (s_hist['delta'] < 0) & (s_hist['delta'] >= -0.10) & (s_hist['dte'] > 2)].copy()
    far_call['dte_bucket'] = far_call['dte'].apply(lambda d: '2-7 DTE' if d<=7 else ('8-15 DTE' if d<=15 else ('16-30 DTE' if d<=30 else ('31-45 DTE' if d<=45 else '46+ DTE'))))
    far_put['dte_bucket'] = far_put['dte'].apply(lambda d: '2-7 DTE' if d<=7 else ('8-15 DTE' if d<=15 else ('16-30 DTE' if d<=30 else ('31-45 DTE' if d<=45 else '46+ DTE'))))
    call_oi_pivot = far_call.groupby(['date_str','dte_bucket'])['open_interest'].sum().unstack(fill_value=0) if 'dte_bucket' in far_call.columns else pd.DataFrame()
    put_oi_pivot = far_put.groupby(['date_str','dte_bucket'])['open_interest'].sum().unstack(fill_value=0) if 'dte_bucket' in far_put.columns else pd.DataFrame()
    dte_buckets_order = ['2-7 DTE','8-15 DTE','16-30 DTE','31-45 DTE','46+ DTE']
    dte_colors = ['#EF553B','#FFA15A','#FECB52','#00CC96','#636EFA']
    # ---------------------------------------

    # ==========================================
    # CHART 8: NET OPEN INTEREST by DTE Bucket
    # ==========================================
    st.divider()
    c_oi, c_oi_desc = st.columns([2, 1])
    with c_oi:
        fig_s7 = make_subplots(specs=[[{"secondary_y": True}]])

        oi_net_pivot = pd.DataFrame()
        if not call_oi_pivot.empty or not put_oi_pivot.empty:
            co = call_oi_pivot.reindex(columns=[b for b in dte_buckets_order if b in call_oi_pivot.columns], fill_value=0) if not call_oi_pivot.empty else pd.DataFrame(0, index=put_oi_pivot.index, columns=[b for b in dte_buckets_order if b in put_oi_pivot.columns])
            po = put_oi_pivot.reindex(columns=[b for b in dte_buckets_order if b in put_oi_pivot.columns], fill_value=0) if not put_oi_pivot.empty else pd.DataFrame(0, index=call_oi_pivot.index, columns=[b for b in dte_buckets_order if b in call_oi_pivot.columns])
            oi_net_pivot = co - po
            oi_net_pivot = oi_net_pivot.reindex(sorted(oi_net_pivot.index), fill_value=0)

        if not oi_net_pivot.empty:
            total_oi = oi_net_pivot.sum(axis=1)
            total_oi_diff3 = total_oi - total_oi.shift(3)
            oi_diff_dict = total_oi_diff3.to_dict()
            oi_val_dict = total_oi.to_dict()

            restricted_dates = fetch_restricted_earnings_dates(selected_ticker)
            all_dates_c8 = sorted(set(agg_vwks_sig['date_str'])) if not agg_vwks_sig.empty else []
            up_arrows = []
            down_arrows = []
            for d in all_dates_c8:
                if 'gap_hl' in locals() and d in gap_hl['date_str'].values:
                    row_hl = gap_hl[gap_hl['date_str'] == d].iloc[0]
                    diff = oi_diff_dict.get(d, np.nan)
                    curr_oi = oi_val_dict.get(d, 0)
                    if pd.notna(diff) and d not in restricted_dates:
                        call_trig = row_hl['call_hl_5d'] and diff < 0 and abs(curr_oi) > 20000
                        put_trig = row_hl['put_hl_5d'] and diff > 0 and abs(curr_oi) > 20000
                        if put_trig:
                            up_arrows.append(d)
                        if call_trig:
                            down_arrows.append(d)

            pos_sum = oi_net_pivot[oi_net_pivot > 0].sum(axis=1).max()
            neg_sum = oi_net_pivot[oi_net_pivot < 0].sum(axis=1).min()
            y_max_c8 = pos_sum * 1.05 if pd.notna(pos_sum) and pos_sum > 0 else 100
            y_min_c8 = neg_sum * 1.05 if pd.notna(neg_sum) and neg_sum < 0 else -100

            offset_up = y_min_c8 * 1.1 if y_min_c8 < 0 else -20
            offset_down = y_min_c8 * 1.15 if y_min_c8 < 0 else -30

            if up_arrows:
                fig_s7.add_trace(go.Scatter(x=up_arrows, y=[offset_up]*len(up_arrows),
                    mode='markers', marker=dict(symbol='triangle-up', size=14, color='#00CC96', line=dict(color='white', width=1)),
                    name='Put VWKS Accumulation', showlegend=False, hoverinfo='skip'), secondary_y=False)
            if down_arrows:
                fig_s7.add_trace(go.Scatter(x=down_arrows, y=[offset_down]*len(down_arrows),
                    mode='markers', marker=dict(symbol='triangle-down', size=14, color='#EF553B', line=dict(color='white', width=1)),
                    name='Call VWKS Accumulation', showlegend=False, hoverinfo='skip'), secondary_y=False)

            for wi, bucket in enumerate(dte_buckets_order):
                if bucket in oi_net_pivot.columns:
                    vals = oi_net_pivot[bucket]
                    if abs(vals).sum() > 0:
                        fig_s7.add_trace(go.Bar(x=oi_net_pivot.index, y=vals,
                            name=bucket, marker_color=dte_colors[wi], showlegend=True), secondary_y=False)

            fig_s7.add_hline(y=0, line_color='white', line_width=1, opacity=0.4, secondary_y=False)

        if not agg_vwks_sig.empty:
            fig_s7.add_trace(go.Scatter(x=agg_vwks_sig['date_str'], y=agg_vwks_sig['VWKS_5D_MA'],
                name="Call VWKS 5D MA", mode='lines+markers', line=dict(color='#00CC96', width=2.5)), secondary_y=True)
        if not agg_put_sig.empty:
            fig_s7.add_trace(go.Scatter(x=agg_put_sig['date_str'], y=agg_put_sig['VWKS_PUT_5D'],
                name="Put VWKS 5D MA", mode='lines+markers', line=dict(color='#EF553B', width=2.5)), secondary_y=True)

        fig_s7.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
            line=dict(color='white', width=2, dash='dot')), secondary_y=True)

        fig_s7.update_layout(title="8. Net Far-OTM Open Interest (Calls − Puts) by DTE",
            template='plotly_dark', barmode='relative', bargap=0,
            height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
            legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(size=9)))
        fig_s7.update_xaxes(type='category', categoryorder='category ascending')
        fig_s7.update_yaxes(title_text="Net Open Interest", secondary_y=False)
        fig_s7.update_yaxes(showgrid=False, secondary_y=True)
        st.plotly_chart(fig_s7, use_container_width=True)
    with c_oi_desc:
        st.info("**Net OI = Call OI minus Put OI for far-OTM options, stacked by DTE.**\n\n"
            "OI represents structural positioning (not daily flow). Changes here reflect shifts in longer-term conviction.\n\n"
            "**VWKS Lines** = 5-day MA for Calls (Green) and Puts (Red).\n\n"
            "**Arrows** = Active accumulation signal (VWKS divergence + supportive 3-day net OI flow).")

    st.divider()
    render_omni_volatility(s_hist, s_hist, key_suffix="tab6")

    # ==========================================
    # MARKET WIDE ARROW SCANNER
    # ==========================================
    st.divider()
    st.subheader("🎯 Market-Wide Accumulation Scanner")
    st.markdown("Scan all tickers for active accumulation arrows on a specific date.")
    
    scan_c1, scan_c2 = st.columns([1, 3])
    with scan_c1:
        scan_date = st.selectbox("Select Scan Date:", available_dates, key="scan_date_sel")
        scan_btn = st.button("Run Scanner", use_container_width=True, type="primary")
    
    if scan_btn:
        with st.spinner(f"Scanning market for signals on {scan_date}..."):
            @st.cache_data(ttl=3600)
            def run_arrow_scanner(target_date, _con, bucket):
                all_d = sorted(df_summary['date'].astype(str).str[:10].unique())
                if target_date not in all_d: return pd.DataFrame()
                
                idx = all_d.index(target_date)
                query = f"SELECT * FROM read_parquet('s3://{bucket}/dashboard_data/scanner_gold.parquet') WHERE date_str = '{target_date}'"
                
                try:
                    target_df = _con.execute(query).df()
                except Exception as e:
                    st.error(f"Scanner Database Error: {e}")
                    return pd.DataFrame()
                
                if target_df.empty: return pd.DataFrame()
                
                # Vectorized filtering to avoid sequential API calls for non-triggered tickers
                call_trig_mask = (target_df['call_hl_5d'] == True) & target_df['net_oi_diff3'].notna() & (target_df['net_oi_diff3'] < 0) & (target_df['net_oi'].abs() > 20000)
                put_trig_mask = (target_df['put_hl_5d'] == True) & target_df['net_oi_diff3'].notna() & (target_df['net_oi_diff3'] > 0) & (target_df['net_oi'].abs() > 20000)
                
                triggered_df = target_df[call_trig_mask | put_trig_mask].copy()
                
                results = []
                for _, row in triggered_df.iterrows():
                    tckr = row['ticker']
                    
                    # Fetch earnings only for triggered tickers
                    restricted = fetch_restricted_earnings_dates(tckr)
                    if target_date in restricted:
                        continue
                        
                    call_trig = (row['call_hl_5d'] == True) and pd.notna(row['net_oi_diff3']) and row['net_oi_diff3'] < 0 and abs(row['net_oi']) > 20000
                    
                    results.append({
                        'Ticker': tckr,
                        'Signal': 'CALL VWKS ACCUMULATION 🔻' if call_trig else 'PUT VWKS ACCUMULATION 🟢 ⬆️',
                        'Spot': row['spot'],
                        'VWKS (5D)': row['VWKS_5D_MA'] if call_trig else row['VWKS_PUT_5D'],
                        '3D Net OI Flow': row['net_oi_diff3'],
                        'Total Net OI': row['net_oi'],
                        'Distance to VWKS (%)': row['call_gap_5d'] if call_trig else row['put_gap_5d']
                    })
                
                return pd.DataFrame(results)

            res_df = run_arrow_scanner(scan_date, db_con, bucket_name)
            if not res_df.empty:
                res_df['Total Net OI'] = res_df['Total Net OI'].apply(lambda x: f"{x:,.0f}")
                res_df['3D Net OI Flow'] = res_df['3D Net OI Flow'].apply(lambda x: f"{x:,.0f}")
                st.dataframe(res_df, use_container_width=True, hide_index=True)
                st.success(f"Found {len(res_df)} tickers with signals on {scan_date}.")
            else:
                st.info(f"No signals found across any tickers on {scan_date}.")

# ==========================================
# TAB 7: TRADE IDEAS
# ==========================================
if active_tab == "🏆 Trade Ideas":
    st.header("🏆 Fresh Trade Idea Models")
    st.markdown("Automated screening for anomalies, decoupling, and accumulation setups.")
    
    # 1. Volatility Surface anomalies
    st.subheader("1. Volatility Surface Anomalies")
    st.markdown("Hunt for anomalies where IV significantly deviates from the normal surface, potentially highlighting large customer buying disguised by 0DTE or MM washing.")
    if not current_chain.empty and spot_price > 0:
        c_anom = current_chain.copy()
        # Filter low volume to focus on real bets
        c_anom = c_anom[c_anom['volume'] > 50].copy()
        # Filter to strikes within +/- 20% of spot
        c_anom = c_anom[(c_anom['strike'] >= spot_price * 0.8) & (c_anom['strike'] <= spot_price * 1.2)].copy()
        
        if not c_anom.empty and 'iv' in c_anom.columns:
            # Drop NAs
            c_anom = c_anom.dropna(subset=['iv', 'dte'])
            # Round strikes to nearest .5 or whole number
            c_anom['strike'] = c_anom['strike'].apply(lambda x: round(x * 2) / 2)
            # Create DTE buckets
            c_anom['dte_bucket'] = pd.cut(c_anom['dte'], bins=[-1, 3, 7, 30, 90, 365, 1000], labels=['0-3', '4-7', '8-30', '31-90', '91-365', '365+'])
            
            # Calculate mean and std per side and dte bucket
            bucket_stats = c_anom.groupby(['side', 'dte_bucket'], observed=False)['iv'].agg(['mean', 'std']).reset_index()
            c_anom = c_anom.merge(bucket_stats, on=['side', 'dte_bucket'], suffixes=('', '_bucket'))
            
            c_anom['z_score'] = (c_anom['iv'] - c_anom['mean']) / (c_anom['std'] + 1e-9)
            anomalies = c_anom[c_anom['z_score'] > 2.0].sort_values('z_score', ascending=False).head(15)
            
            if not anomalies.empty:
                fig_anom = px.scatter(
                    anomalies, x="strike", y="iv", color="side", size="volume", 
                    hover_data=["expiration", "dte", "z_score", "open_interest"],
                    title="Top Volatility Surface Anomalies (Z-Score > 2.0)",
                    template="plotly_dark", color_discrete_map={'CALL': '#00CC96', 'PUT': '#EF553B'}
                )
                fig_anom.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text="Spot")
                st.plotly_chart(fig_anom, use_container_width=True)
                
                disp_anom = anomalies[['expiration', 'strike', 'side', 'iv', 'volume', 'open_interest', 'z_score']].copy()
                st.dataframe(disp_anom.style.format({'iv': '{:.2%}', 'z_score': '{:.2f}', 'strike': '{:g}'}), use_container_width=True)
            else:
                st.info("No significant volatility surface anomalies detected today.")
        else:
            st.warning("Insufficient data for Volatility Anomalies.")
            
    # 2. Volatility decoupling
    st.divider()
    st.subheader("2. Volatility Decoupling Tracker")
    st.markdown("Identify days where ATM IV decoupled from Spot Price movements (e.g. Spot Up + IV Up, or Spot Down + IV Down).")
    
    valid_dates_dec = sorted(ticker_chain['date_str'].dropna().unique())
    if len(valid_dates_dec) > 10:
        hist_dec = ticker_chain.groupby('date_str')['underlying_price'].first().reset_index()
        
        atm_ivs = []
        for d in hist_dec['date_str']:
            chain_d = ticker_chain[ticker_chain['date_str'] == d]
            if not chain_d.empty:
                s = chain_d['underlying_price'].iloc[0]
                chain_d_copy = chain_d.copy()
                chain_d_copy['dist'] = (chain_d_copy['strike'] - s).abs()
                min_dist = chain_d_copy['dist'].min()
                a_iv = chain_d_copy[chain_d_copy['dist'] == min_dist]['iv'].mean()
                atm_ivs.append(a_iv)
            else:
                atm_ivs.append(np.nan)
                
        hist_dec['atm_iv'] = atm_ivs
        hist_dec = hist_dec.dropna()
        
        hist_dec['spot_ret'] = hist_dec['underlying_price'].pct_change()
        hist_dec['iv_ret'] = hist_dec['atm_iv'].pct_change()
        
        hist_dec['decoupled'] = np.where((hist_dec['spot_ret'] > 0.005) & (hist_dec['iv_ret'] > 0.02), 'Call Buying (Spot Up + IV Up)',
                              np.where((hist_dec['spot_ret'] < -0.005) & (hist_dec['iv_ret'] < -0.02), 'Put Selling (Spot Down + IV Down)', 'Normal'))
                              
        fig_dec = make_subplots(specs=[[{"secondary_y": True}]])
        fig_dec.add_trace(go.Scatter(x=hist_dec['date_str'], y=hist_dec['underlying_price'], name="Spot Price", line=dict(color='white', width=2)), secondary_y=False)
        fig_dec.add_trace(go.Scatter(x=hist_dec['date_str'], y=hist_dec['atm_iv'], name="ATM IV", line=dict(color='#FECB52', width=2)), secondary_y=True)
        
        anom_up = hist_dec[hist_dec['decoupled'] == 'Call Buying (Spot Up + IV Up)']
        anom_dn = hist_dec[hist_dec['decoupled'] == 'Put Selling (Spot Down + IV Down)']
        
        if not anom_up.empty:
            fig_dec.add_trace(go.Scatter(x=anom_up['date_str'], y=anom_up['underlying_price'], mode='markers', name='Call Buying (Decoupled)', marker=dict(color='#00CC96', size=12, symbol='triangle-up')), secondary_y=False)
        if not anom_dn.empty:
            fig_dec.add_trace(go.Scatter(x=anom_dn['date_str'], y=anom_dn['underlying_price'], mode='markers', name='Put Selling (Decoupled)', marker=dict(color='#EF553B', size=12, symbol='triangle-down')), secondary_y=False)
            
        fig_dec.update_layout(template="plotly_dark", hovermode="x unified", title="Spot vs ATM IV Macro Decoupling", height=400)
        fig_dec.update_yaxes(title_text="Spot Price", secondary_y=False)
        fig_dec.update_yaxes(title_text="ATM IV", secondary_y=True)
        st.plotly_chart(fig_dec, use_container_width=True)

    # 3. OI Accumulation Efficiency Ratio
    st.divider()
    st.subheader("3. OI Accumulation Efficiency Ratio")
    st.markdown("Ratio of **Δ OI / Volume** from the previous day. High efficiency (>70%) on 7-45 DTE expirations flags 'sticky' institutional positioning rather than day-trading washes.")
    
    dates = valid_dates_dec
    if len(dates) >= 2:
        idx = dates.index(selected_date) if selected_date in dates else 0
        if idx > 0:
            yest_date = dates[idx - 1]
            df_tdy = current_chain.copy()
            df_yest = ticker_chain[ticker_chain['date_str'] == yest_date][['expiration', 'strike', 'side', 'open_interest', 'volume']].copy()
            
            df_eff = df_tdy.merge(df_yest, on=['expiration', 'strike', 'side'], suffixes=('', '_yest'))
            df_eff['oi_delta'] = df_eff['open_interest'] - df_eff['open_interest_yest']
            
            # Efficiency based on yesterday's volume
            df_eff['strike'] = df_eff['strike'].apply(lambda x: round(x * 2) / 2)
            df_eff = df_eff[(df_eff['volume_yest'] > 100) & (df_eff['dte'].between(7, 45))].copy()
            df_eff['efficiency'] = np.where(df_eff['volume_yest'] > 0, df_eff['oi_delta'] / df_eff['volume_yest'], 0)
            
            highly_eff = df_eff[df_eff['efficiency'] > 0.70].sort_values('efficiency', ascending=False)
            
            if not highly_eff.empty:
                disp_eff = highly_eff[['expiration', 'strike', 'side', 'oi_delta', 'volume_yest', 'efficiency']].copy()
                st.dataframe(disp_eff.style.format({'efficiency': '{:.1%}', 'oi_delta': '+{:,.0f}', 'volume_yest': '{:,.0f}', 'strike': '{:g}'}), use_container_width=True)
            else:
                st.info("No high-efficiency ( >70% ) OI builds detected in the 7-45 DTE range based on yesterday's volume.")
        else:
            st.warning("No previous day data available to calculate OI efficiency. Please select a date with a prior trading day.")
            
    # 4. Term Structure Shift
    st.divider()
    st.subheader("4. The 'Term Structure' Shift")
    st.markdown("Detects unusual shifts in volume distribution across expirations compared to a 10-day historical average. Sudden volume shifting to long-term dates indicates institutional entry.")
    
    if len(dates) > 10:
        idx = dates.index(selected_date) if selected_date in dates else len(dates)-1
        hist_10d_dates = dates[max(0, idx - 10):idx]
        hist_10d_chain = ticker_chain[ticker_chain['date_str'].isin(hist_10d_dates)].copy()
        
        def categorize_dte(dte):
            if pd.isna(dte): return 'Unknown'
            if dte <= 7: return '0-7 DTE'
            elif dte <= 30: return '8-30 DTE'
            elif dte <= 60: return '31-60 DTE'
            elif dte <= 90: return '61-90 DTE'
            else: return '90+ DTE'
            
        hist_10d_chain['dte_cat'] = hist_10d_chain['dte'].apply(categorize_dte)
        df_tdy = current_chain.copy()
        df_tdy['dte_cat'] = df_tdy['dte'].apply(categorize_dte)
        
        hist_daily_cat = hist_10d_chain.groupby(['date_str', 'dte_cat'])['volume'].sum().reset_index()
        hist_daily_total = hist_10d_chain.groupby('date_str')['volume'].sum().reset_index()
        
        hist_merged = hist_daily_cat.merge(hist_daily_total, on='date_str', suffixes=('', '_total'))
        hist_merged['pct_of_total'] = np.where(hist_merged['volume_total'] > 0, hist_merged['volume'] / hist_merged['volume_total'], 0)
        
        hist_avg_dist = hist_merged.groupby('dte_cat')['pct_of_total'].mean().reset_index().rename(columns={'pct_of_total': 'hist_avg_pct'})
        
        tdy_cat_vol = df_tdy.groupby('dte_cat')['volume'].sum().reset_index()
        tdy_total_vol = tdy_cat_vol['volume'].sum()
        tdy_cat_vol['tdy_pct'] = np.where(tdy_total_vol > 0, tdy_cat_vol['volume'] / tdy_total_vol, 0)
        
        shift_df = hist_avg_dist.merge(tdy_cat_vol, on='dte_cat', how='outer').fillna(0)
        shift_df['shift'] = shift_df['tdy_pct'] - shift_df['hist_avg_pct']
        
        # Sort DTE categories logically
        cat_order = ['0-7 DTE', '8-30 DTE', '31-60 DTE', '61-90 DTE', '90+ DTE']
        shift_df['dte_cat'] = pd.Categorical(shift_df['dte_cat'], categories=cat_order, ordered=True)
        shift_df = shift_df.sort_values('dte_cat')
        
        fig_shift = go.Figure()
        fig_shift.add_trace(go.Bar(x=shift_df['dte_cat'], y=shift_df['hist_avg_pct'], name="10-Day Avg %", marker_color='rgba(255, 255, 255, 0.3)'))
        fig_shift.add_trace(go.Bar(x=shift_df['dte_cat'], y=shift_df['tdy_pct'], name="Today's %", marker_color='#FECB52'))
        fig_shift.update_layout(template="plotly_dark", barmode='group', height=400, yaxis_tickformat='.1%')
        st.plotly_chart(fig_shift, use_container_width=True)
        
        significant_shifts = shift_df[(shift_df['shift'] > 0.10) & (shift_df['dte_cat'].isin(['31-60 DTE', '61-90 DTE', '90+ DTE']))]
        if not significant_shifts.empty:
            st.success("🚨 **INSTITUTIONAL SHIFT DETECTED:** Significant volume has shifted to longer-term expirations today compared to historical averages.")

# ==========================================
# TAB 8: INSTITUTIONAL SURFACE HEATMAP (LADDER)
# ==========================================
if active_tab == "🌡️ Surface Heatmap":
    st.header("🌡️ Options Surface Heatmap")
    st.markdown("A 3D grid visualizing exposure and flow across the entire matrix of strikes and expirations.")

    # --- CONTROLS ---
    c_heat_met, c_heat_side, c_heat_dte, c_heat_strike = st.columns([2, 1, 1, 1])
    with c_heat_met:
        # NEW: Added Notional Premium metric
        heat_metric = st.selectbox("Select Display Metric:",
                                   ["Gamma Exposure (Net GEX)", "Notional Delta (Net DEX)",
                                    "Notional Premium (Net Prem)", "Total Volume", "Daily Δ Open Interest",
                                    "Total Open Interest (+ Daily Δ)", "Volume vs OI (Vol - OI)"],
                                   label_visibility="collapsed")
    with c_heat_side:
        heat_side = st.radio("Side:", ["Both", "Calls Only", "Puts Only"], horizontal=True,
                             label_visibility="collapsed")
    with c_heat_dte:
        heat_max_dte = st.slider("Max DTE Window:", min_value=7, max_value=180, value=45)
    with c_heat_strike:
        heat_strike_range = st.slider("Strike Range (+/- % from Spot):", min_value=5, max_value=30, value=15)

    if not current_chain.empty and spot_price > 0:
        df_heat = current_chain.copy()
        if heat_side == "Calls Only":
            df_heat = df_heat[df_heat['side'] == 'CALL']
        elif heat_side == "Puts Only":
            df_heat = df_heat[df_heat['side'] == 'PUT']

        df_heat = df_heat[(df_heat['dte'] <= heat_max_dte) &
                          (df_heat['strike'] >= spot_price * (1 - heat_strike_range / 100)) &
                          (df_heat['strike'] <= spot_price * (1 + heat_strike_range / 100))].copy()

        dates = sorted(ticker_chain['date_str'].dropna().unique())
        curr_idx = dates.index(selected_date) if selected_date in dates else 0
        yest_date = dates[curr_idx - 1] if curr_idx > 0 else None

        if yest_date:
            df_yest = ticker_chain[ticker_chain['date_str'] == yest_date][
                ['expiration', 'strike', 'side', 'open_interest']]
            df_heat = df_heat.merge(df_yest, on=['expiration', 'strike', 'side'], how='left',
                                    suffixes=('', '_yest')).fillna({'open_interest_yest': 0})
            df_heat['oi_delta'] = df_heat['open_interest'] - df_heat['open_interest_yest']
        else:
            df_heat['oi_delta'] = 0

        # Calculate Selected Metric
        if heat_metric == "Gamma Exposure (Net GEX)":
            df_heat['val'] = np.where(df_heat['side'] == 'CALL',
                                      df_heat['gamma'] * df_heat['open_interest'] * 100 * spot_price,
                                      -df_heat['gamma'] * df_heat['open_interest'] * 100 * spot_price)
            df_heat['sub_val'] = 0
            prefix, is_diverging = "$", True

        elif heat_metric == "Notional Delta (Net DEX)":
            df_heat['val'] = np.where(df_heat['side'] == 'CALL',
                                      df_heat['delta'].abs() * df_heat['open_interest'] * 100 * spot_price,
                                      -df_heat['delta'].abs() * df_heat['open_interest'] * 100 * spot_price)
            df_heat['sub_val'] = 0
            prefix, is_diverging = "$", True

        elif heat_metric == "Notional Premium (Net Prem)":
            # NEW: Premium mapping. Call Premium is positive (+), Put Premium is negative (-)
            df_heat['val'] = np.where(df_heat['side'] == 'CALL', df_heat['open_interest'] * df_heat['last_price'] * 100,
                                      -df_heat['open_interest'] * df_heat['last_price'] * 100)
            df_heat['sub_val'] = 0
            prefix, is_diverging = "$", True

        elif heat_metric == "Total Volume":
            df_heat['val'] = df_heat['volume']
            df_heat['sub_val'] = 0
            prefix, is_diverging = "", False

        elif heat_metric == "Daily Δ Open Interest":
            df_heat['val'] = np.where(df_heat['side'] == 'CALL', df_heat['oi_delta'], -df_heat['oi_delta'])
            df_heat['sub_val'] = 0
            prefix, is_diverging = "", True

        elif heat_metric == "Total Open Interest (+ Daily Δ)":
            df_heat['val'] = df_heat['open_interest']
            df_heat['sub_val'] = df_heat['oi_delta']
            prefix, is_diverging = "", False

        elif heat_metric == "Volume vs OI (Vol - OI)":
            df_heat['val'] = df_heat['volume'] - df_heat['open_interest']
            df_heat['sub_val'] = 0
            prefix, is_diverging = "", True

        if not df_heat.empty:
            agg_heat = df_heat.groupby(['strike', 'expiration'])[['val', 'sub_val']].sum().reset_index()


            def format_num(x, pref=""):
                if pd.isna(x): return ""
                sign = "-" if x < 0 else ""
                val = abs(x)
                if val >= 1_000_000:
                    return f"{sign}{pref}{val / 1_000_000:.1f}M"
                elif val >= 1_000:
                    return f"{sign}{pref}{val / 1_000:.1f}K"
                else:
                    return f"{sign}{pref}{val:.0f}"


            def generate_cell_text(row):
                v, sv = row['val'], row['sub_val']
                if v == 0 and sv == 0: return ""
                main_str = format_num(v, prefix) if v != 0 else "0"
                if heat_metric == "Total Open Interest (+ Daily Δ)":
                    sub_sign = "+" if sv > 0 else ""
                    sub_str = format_num(sv, "") if sv != 0 else "0"
                    return f"{main_str} ({sub_sign}{sub_str})"
                return main_str


            agg_heat['text_col'] = agg_heat.apply(generate_cell_text, axis=1)

            pivot_matrix = agg_heat.pivot(index='strike', columns='expiration', values='val').fillna(0).sort_index(
                ascending=True)
            text_matrix = agg_heat.pivot(index='strike', columns='expiration', values='text_col').fillna("").sort_index(
                ascending=True)

            if is_diverging:
                color_scale = [[0.0, '#FF3333'], [0.499, '#111111'], [0.5, '#222222'], [1.0, '#00FF00']]
                zmid = 0
            else:
                color_scale = [[0.0, '#111111'], [1.0, '#00FF00']]
                zmid = None

            fig_hm = go.Figure(data=go.Heatmap(
                z=pivot_matrix.values, x=pivot_matrix.columns, y=pivot_matrix.index, text=text_matrix.values,
                texttemplate="%{text}", colorscale=color_scale, zmid=zmid, showscale=False, xgap=2, ygap=2,
                hovertemplate="<b>Strike:</b> $%{y}<br><b>Exp:</b> %{x}<br><b>Data:</b> %{text}<extra></extra>"
            ))

            fig_hm.add_hline(y=spot_price, line_dash="solid", line_color="white", line_width=2, annotation_text="Spot",
                             annotation_position="left")
            fig_hm.update_layout(template='plotly_dark', height=850, margin=dict(l=10, r=10, t=30, b=10),
                                 xaxis=dict(title=None, side='top', tickangle=0, type='category', categoryorder='array',
                                            categoryarray=pivot_matrix.columns),
                                 yaxis=dict(title="Strike Price", tickmode='array', tickvals=pivot_matrix.index,
                                            tickformat=".1f"))

            st.plotly_chart(fig_hm, use_container_width=True)
            
            # --- KPI CONTEXT TABLE ---
            st.divider()
            st.subheader(f"Historical KPI Context: {heat_metric} (Single Contract)")
            st.markdown("Context is based on individual contracts over the last 90 days (excluding < 2 DTE).")
            
            dates_all = sorted(ticker_chain['date_str'].dropna().unique())
            dates_90d = dates_all[-90:] if len(dates_all) > 90 else dates_all
            chain_90d = ticker_chain[ticker_chain['date_str'].isin(dates_90d)].copy()
            
            # Filter out < 2 DTE
            chain_90d = chain_90d[chain_90d['dte'] >= 2].copy()
            
            if heat_metric == "Total Volume":
                chain_90d['val'] = chain_90d['volume']
            elif heat_metric == "Total Open Interest (+ Daily Δ)":
                chain_90d['val'] = chain_90d['open_interest']
            elif heat_metric == "Volume vs OI (Vol - OI)":
                chain_90d['val'] = chain_90d['volume'] - chain_90d['open_interest']
            elif heat_metric == "Gamma Exposure (Net GEX)":
                chain_90d['val'] = np.where(chain_90d['side'] == 'CALL', pd.to_numeric(chain_90d['gamma'], errors='coerce') * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'], -pd.to_numeric(chain_90d['gamma'], errors='coerce') * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'])
            elif heat_metric == "Notional Delta (Net DEX)":
                chain_90d['val'] = np.where(chain_90d['side'] == 'CALL', pd.to_numeric(chain_90d['delta'], errors='coerce').abs() * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'], -pd.to_numeric(chain_90d['delta'], errors='coerce').abs() * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'])
            elif heat_metric == "Notional Premium (Net Prem)":
                chain_90d['val'] = np.where(chain_90d['side'] == 'CALL', chain_90d['open_interest'] * chain_90d['last_price'] * 100, -chain_90d['open_interest'] * chain_90d['last_price'] * 100)
            else:
                chain_90d['val'] = np.nan
                
            if not chain_90d.empty and not df_heat.empty:
                # If metric is diverging, take absolute values for the distribution (magnitude of size)
                if heat_metric in ["Gamma Exposure (Net GEX)", "Notional Delta (Net DEX)", "Notional Premium (Net Prem)", "Volume vs OI (Vol - OI)", "Daily Δ Open Interest"]:
                    chain_90d['val'] = chain_90d['val'].abs()
                    today_max_val = df_heat['val'].abs().max()
                else:
                    today_max_val = df_heat['val'].max()
                
                # Get the Daily Maximum contract size for the last 90 days
                daily_maxes = chain_90d.groupby('date_str')['val'].max().dropna()
                
                if len(daily_maxes) > 0:
                    avg_90d = daily_maxes.mean()
                    p90 = daily_maxes.quantile(0.90)
                    p_rank = (daily_maxes <= today_max_val).mean() * 100
                    
                    c1, c2, c3, c4 = st.columns(4)
                    prefix_str = "$" if "Notional" in heat_metric or "Gamma" in heat_metric else ""
                    c1.metric("Today's Max (Selected View)", f"{prefix_str}{today_max_val:,.0f}")
                    c2.metric("90-Day Avg of Daily Maxes", f"{prefix_str}{avg_90d:,.0f}")
                    c3.metric("90th Percentile of Daily Maxes", f"{prefix_str}{p90:,.0f}")
                    c4.metric("Current Max Percentile Rank", f"{p_rank:.0f}%")
# TAB 8: INSTITUTIONAL SURFACE HEATMAP (LADDER)
# ==========================================
if active_tab == "🌡️ Surface Heatmap":
    st.header("🌡️ Options Surface Heatmap")
    st.markdown("A 3D grid visualizing exposure and flow across the entire matrix of strikes and expirations.")

    # --- CONTROLS ---
    c_heat_met, c_heat_side, c_heat_dte, c_heat_strike = st.columns([2, 1, 1, 1])
    with c_heat_met:
        # NEW: Added Notional Premium metric
        heat_metric = st.selectbox("Select Display Metric:",
                                   ["Gamma Exposure (Net GEX)", "Notional Delta (Net DEX)",
                                    "Notional Premium (Net Prem)", "Total Volume", "Daily Δ Open Interest",
                                    "Total Open Interest (+ Daily Δ)", "Volume vs OI (Vol - OI)"],
                                   label_visibility="collapsed")
    with c_heat_side:
        heat_side = st.radio("Side:", ["Both", "Calls Only", "Puts Only"], horizontal=True,
                             label_visibility="collapsed")
    with c_heat_dte:
        heat_max_dte = st.slider("Max DTE Window:", min_value=7, max_value=180, value=45)
    with c_heat_strike:
        heat_strike_range = st.slider("Strike Range (+/- % from Spot):", min_value=5, max_value=30, value=15)

    if not current_chain.empty and spot_price > 0:
        df_heat = current_chain.copy()
        if heat_side == "Calls Only":
            df_heat = df_heat[df_heat['side'] == 'CALL']
        elif heat_side == "Puts Only":
            df_heat = df_heat[df_heat['side'] == 'PUT']

        df_heat = df_heat[(df_heat['dte'] <= heat_max_dte) &
                          (df_heat['strike'] >= spot_price * (1 - heat_strike_range / 100)) &
                          (df_heat['strike'] <= spot_price * (1 + heat_strike_range / 100))].copy()

        dates = sorted(ticker_chain['date_str'].dropna().unique())
        curr_idx = dates.index(selected_date) if selected_date in dates else 0
        yest_date = dates[curr_idx - 1] if curr_idx > 0 else None

        if yest_date:
            df_yest = ticker_chain[ticker_chain['date_str'] == yest_date][
                ['expiration', 'strike', 'side', 'open_interest']]
            df_heat = df_heat.merge(df_yest, on=['expiration', 'strike', 'side'], how='left',
                                    suffixes=('', '_yest')).fillna({'open_interest_yest': 0})
            df_heat['oi_delta'] = df_heat['open_interest'] - df_heat['open_interest_yest']
        else:
            df_heat['oi_delta'] = 0

        # Calculate Selected Metric
        if heat_metric == "Gamma Exposure (Net GEX)":
            df_heat['val'] = np.where(df_heat['side'] == 'CALL',
                                      df_heat['gamma'] * df_heat['open_interest'] * 100 * spot_price,
                                      -df_heat['gamma'] * df_heat['open_interest'] * 100 * spot_price)
            df_heat['sub_val'] = 0
            prefix, is_diverging = "$", True

        elif heat_metric == "Notional Delta (Net DEX)":
            df_heat['val'] = np.where(df_heat['side'] == 'CALL',
                                      df_heat['delta'].abs() * df_heat['open_interest'] * 100 * spot_price,
                                      -df_heat['delta'].abs() * df_heat['open_interest'] * 100 * spot_price)
            df_heat['sub_val'] = 0
            prefix, is_diverging = "$", True

        elif heat_metric == "Notional Premium (Net Prem)":
            # NEW: Premium mapping. Call Premium is positive (+), Put Premium is negative (-)
            df_heat['val'] = np.where(df_heat['side'] == 'CALL', df_heat['open_interest'] * df_heat['last_price'] * 100,
                                      -df_heat['open_interest'] * df_heat['last_price'] * 100)
            df_heat['sub_val'] = 0
            prefix, is_diverging = "$", True

        elif heat_metric == "Total Volume":
            df_heat['val'] = df_heat['volume']
            df_heat['sub_val'] = 0
            prefix, is_diverging = "", False

        elif heat_metric == "Daily Δ Open Interest":
            df_heat['val'] = np.where(df_heat['side'] == 'CALL', df_heat['oi_delta'], -df_heat['oi_delta'])
            df_heat['sub_val'] = 0
            prefix, is_diverging = "", True

        elif heat_metric == "Total Open Interest (+ Daily Δ)":
            df_heat['val'] = df_heat['open_interest']
            df_heat['sub_val'] = df_heat['oi_delta']
            prefix, is_diverging = "", False

        elif heat_metric == "Volume vs OI (Vol - OI)":
            df_heat['val'] = df_heat['volume'] - df_heat['open_interest']
            df_heat['sub_val'] = 0
            prefix, is_diverging = "", True

        if not df_heat.empty:
            agg_heat = df_heat.groupby(['strike', 'expiration'])[['val', 'sub_val']].sum().reset_index()


            def format_num(x, pref=""):
                if pd.isna(x): return ""
                sign = "-" if x < 0 else ""
                val = abs(x)
                if val >= 1_000_000:
                    return f"{sign}{pref}{val / 1_000_000:.1f}M"
                elif val >= 1_000:
                    return f"{sign}{pref}{val / 1_000:.1f}K"
                else:
                    return f"{sign}{pref}{val:.0f}"


            def generate_cell_text(row):
                v, sv = row['val'], row['sub_val']
                if v == 0 and sv == 0: return ""
                main_str = format_num(v, prefix) if v != 0 else "0"
                if heat_metric == "Total Open Interest (+ Daily Δ)":
                    sub_sign = "+" if sv > 0 else ""
                    sub_str = format_num(sv, "") if sv != 0 else "0"
                    return f"{main_str} ({sub_sign}{sub_str})"
                return main_str


            agg_heat['text_col'] = agg_heat.apply(generate_cell_text, axis=1)

            pivot_matrix = agg_heat.pivot(index='strike', columns='expiration', values='val').fillna(0).sort_index(
                ascending=True)
            text_matrix = agg_heat.pivot(index='strike', columns='expiration', values='text_col').fillna("").sort_index(
                ascending=True)

            if is_diverging:
                color_scale = [[0.0, '#FF3333'], [0.499, '#111111'], [0.5, '#222222'], [1.0, '#00FF00']]
                zmid = 0
            else:
                color_scale = [[0.0, '#111111'], [1.0, '#00FF00']]
                zmid = None

            fig_hm = go.Figure(data=go.Heatmap(
                z=pivot_matrix.values, x=pivot_matrix.columns, y=pivot_matrix.index, text=text_matrix.values,
                texttemplate="%{text}", colorscale=color_scale, zmid=zmid, showscale=False, xgap=2, ygap=2,
                hovertemplate="<b>Strike:</b> $%{y}<br><b>Exp:</b> %{x}<br><b>Data:</b> %{text}<extra></extra>"
            ))

            fig_hm.add_hline(y=spot_price, line_dash="solid", line_color="white", line_width=2, annotation_text="Spot",
                             annotation_position="left")
            fig_hm.update_layout(template='plotly_dark', height=850, margin=dict(l=10, r=10, t=30, b=10),
                                 xaxis=dict(title=None, side='top', tickangle=0, type='category', categoryorder='array',
                                            categoryarray=pivot_matrix.columns),
                                 yaxis=dict(title="Strike Price", tickmode='array', tickvals=pivot_matrix.index,
                                            tickformat=".1f"))

            st.plotly_chart(fig_hm, use_container_width=True)
            
            # --- KPI CONTEXT TABLE ---
            st.divider()
            st.subheader(f"Historical KPI Context: {heat_metric} (Single Contract)")
            st.markdown("Context is based on individual contracts over the last 90 days (excluding < 2 DTE).")
            
            dates_all = sorted(ticker_chain['date_str'].dropna().unique())
            dates_90d = dates_all[-90:] if len(dates_all) > 90 else dates_all
            chain_90d = ticker_chain[ticker_chain['date_str'].isin(dates_90d)].copy()
            
            # Filter out < 2 DTE
            chain_90d = chain_90d[chain_90d['dte'] >= 2].copy()
            
            if heat_metric == "Total Volume":
                chain_90d['val'] = chain_90d['volume']
            elif heat_metric == "Total Open Interest (+ Daily Δ)":
                chain_90d['val'] = chain_90d['open_interest']
            elif heat_metric == "Volume vs OI (Vol - OI)":
                chain_90d['val'] = chain_90d['volume'] - chain_90d['open_interest']
            elif heat_metric == "Gamma Exposure (Net GEX)":
                chain_90d['val'] = np.where(chain_90d['side'] == 'CALL', pd.to_numeric(chain_90d['gamma'], errors='coerce') * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'], -pd.to_numeric(chain_90d['gamma'], errors='coerce') * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'])
            elif heat_metric == "Notional Delta (Net DEX)":
                chain_90d['val'] = np.where(chain_90d['side'] == 'CALL', pd.to_numeric(chain_90d['delta'], errors='coerce').abs() * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'], -pd.to_numeric(chain_90d['delta'], errors='coerce').abs() * chain_90d['open_interest'] * 100 * chain_90d['underlying_price'])
            elif heat_metric == "Notional Premium (Net Prem)":
                chain_90d['val'] = np.where(chain_90d['side'] == 'CALL', chain_90d['open_interest'] * chain_90d['last_price'] * 100, -chain_90d['open_interest'] * chain_90d['last_price'] * 100)
            else:
                chain_90d['val'] = np.nan
                
            if not chain_90d.empty and not df_heat.empty:
                # If metric is diverging, take absolute values for the distribution (magnitude of size)
                if heat_metric in ["Gamma Exposure (Net GEX)", "Notional Delta (Net DEX)", "Notional Premium (Net Prem)", "Volume vs OI (Vol - OI)", "Daily Δ Open Interest"]:
                    chain_90d['val'] = chain_90d['val'].abs()
                    today_max_val = df_heat['val'].abs().max()
                else:
                    today_max_val = df_heat['val'].max()
                
                # Get the Daily Maximum contract size for the last 90 days
                daily_maxes = chain_90d.groupby('date_str')['val'].max().dropna()
                
                if len(daily_maxes) > 0:
                    avg_90d = daily_maxes.mean()
                    p90 = daily_maxes.quantile(0.90)
                    p_rank = (daily_maxes <= today_max_val).mean() * 100
                    
                    c1, c2, c3, c4 = st.columns(4)
                    prefix_str = "$" if "Notional" in heat_metric or "Gamma" in heat_metric else ""
                    c1.metric("Today's Max (Selected View)", f"{prefix_str}{today_max_val:,.0f}")
                    c2.metric("90-Day Avg of Daily Maxes", f"{prefix_str}{avg_90d:,.0f}")
                    c3.metric("90th Percentile of Daily Maxes", f"{prefix_str}{p90:,.0f}")
                    c4.metric("Current Max Percentile Rank", f"{p_rank:.0f}%")
                else:
                    st.info(f"Historical context unavailable for {heat_metric}.")
            else:
                st.info(f"Historical context unavailable for {heat_metric}.")

        else:
            st.warning("No data found for this specific DTE and Strike range combination.")

# ==========================================
# TAB 8: SHORT VOLUME
# ==========================================
if active_tab == "📉 Short Volume":
    st.header(f"📉 FINRA Advanced Short Volume Models for {selected_ticker}")
    st.markdown("Multi-model analysis combining off-exchange short selling activity with options and price data.")
    
    finra_path = f"s3://{bucket_name}/dashboard_data/finra_short_volume_gold.parquet"
    
    try:
        # Load FINRA data for selected ticker (Last 365 days for performance)
        query = f"SELECT * FROM read_parquet('{finra_path}') WHERE Symbol = '{selected_ticker}' AND Date >= current_date - INTERVAL 365 DAYS ORDER BY Date ASC"
        df_finra = db_con.execute(query).df()
    except Exception as e:
        df_finra = pd.DataFrame()
        
    if df_finra.empty:
        st.warning(f"No FINRA short volume data found for {selected_ticker}. Backfill may be required or data does not exist.")
    else:
        # Merge FINRA data with ticker_summary for Price and Options data
        # Ensure dates match for merging
        df_finra['date_str'] = df_finra['Date'].dt.strftime('%Y-%m-%d')
        
        # Merge with ticker_summary
        if not ticker_summary.empty:
            merged_df = df_finra.merge(ticker_summary[['date_str', 'total_volume', 'put_call_ratio_vol']], on='date_str', how='left')
        else:
            merged_df = df_finra.copy()
            merged_df['put_call_ratio_vol'] = np.nan
            
        # Get daily price from yfinance (1 year of history)
        import yfinance as yf
        try:
            yf_ticker = yf.Ticker(selected_ticker)
            hist = yf_ticker.history(period="1y")
            hist = hist.reset_index()
            # yfinance returns timezone-aware dates, need to format to string
            hist['date_str'] = pd.to_datetime(hist['Date'], utc=True).dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
            daily_price = hist[['date_str', 'Close']].rename(columns={'Close': 'close'})
            merged_df = merged_df.merge(daily_price, on='date_str', how='left')
        except Exception as e:
            st.warning(f"Failed to fetch price from yfinance: {e}")
            merged_df['close'] = np.nan
            
        # Merge with ticker_chain for Net Gamma
        if not ticker_chain.empty:
            # Calculate daily net gamma
            daily_gamma = ticker_chain.groupby('date_str').apply(
                lambda x: (x['gamma'] * x['open_interest'] * 100 * np.where(x['side']=='CALL', 1, -1)).sum()
            ).rename('net_gamma').reset_index()
            merged_df = merged_df.merge(daily_gamma, on='date_str', how='left')
        else:
            merged_df['net_gamma'] = np.nan

        # Fill NAs with forward fill for missing options data on some days
        merged_df.ffill(inplace=True)
        
        # Base Metrics calculation
        merged_df['ShortVolPct_10d_MA'] = merged_df['ShortVolPct'].rolling(window=10).mean()
        merged_df['ShortVolPct_30d_MA'] = merged_df['ShortVolPct'].rolling(window=30).mean()
        merged_df['Price_10d_MA'] = merged_df['close'].rolling(window=10).mean()
        merged_df['PCR_10d_MA'] = merged_df['put_call_ratio_vol'].rolling(window=10).mean()
        
        # Forward Return Calculations
        # Note: shift(-X) looks X rows ahead in the dataframe (future returns)
        merged_df['t+3_return'] = merged_df['close'].shift(-3) / merged_df['close'] - 1
        merged_df['t+5_return'] = merged_df['close'].shift(-5) / merged_df['close'] - 1
        merged_df['t+10_return'] = merged_df['close'].shift(-10) / merged_df['close'] - 1

        # Z-Score Calculation (90 day rolling)
        merged_df['ShortVolPct_90d_mean'] = merged_df['ShortVolPct'].rolling(window=90).mean()
        merged_df['ShortVolPct_90d_std'] = merged_df['ShortVolPct'].rolling(window=90).std()
        merged_df['Z_Score'] = (merged_df['ShortVolPct'] - merged_df['ShortVolPct_90d_mean']) / merged_df['ShortVolPct_90d_std']

        # ADVANCED MODELS CALCULATIONS
        # 2A: MM Hedging Divergence
        merged_df['MM_Hedging_Flag'] = (merged_df['ShortVolPct'] > merged_df['ShortVolPct_30d_MA']) & \
                                       (merged_df['put_call_ratio_vol'] < 0.8) & \
                                       (merged_df['close'] > merged_df['Price_10d_MA'])
        
        # 3B: Z-Score MACD
        merged_df['Z_Score_EMA5'] = merged_df['Z_Score'].ewm(span=5, adjust=False).mean()
        merged_df['Z_Score_EMA10'] = merged_df['Z_Score'].ewm(span=10, adjust=False).mean()
        
        # 4: Buy Ratio & Hidden Accumulation
        merged_df['Implied_Long_Vol'] = merged_df['TotalVolume'] - merged_df['ShortVolume']
        merged_df['Implied_Long_5d'] = merged_df['Implied_Long_Vol'].rolling(window=5).sum()
        merged_df['ShortVol_5d'] = merged_df['ShortVolume'].rolling(window=5).sum()
        merged_df['Buy_Ratio_5d'] = merged_df['Implied_Long_5d'] / merged_df['ShortVol_5d'].replace(0, np.nan)
        merged_df['Buy_Ratio_30d_MA'] = merged_df['Buy_Ratio_5d'].rolling(window=30).mean()

        st.divider()

        # ==========================================
        # MODEL 1: SHORT VOLUME SQUEEZE SCORE (SVSS)
        # ==========================================
        st.subheader("🔥 Model 1: Short Volume Squeeze Score (SVSS)")
        st.markdown("Identifies setups where heavy shorting is fighting strong upward momentum, indicating shorts may be trapped.")
        
        latest = merged_df.iloc[-1]
        
        # Calculate SVSS Logic
        svss_score = 0
        if latest['ShortVolPct'] > latest['ShortVolPct_30d_MA']: svss_score += 30
        if latest['ShortVolPct'] > 0.50: svss_score += 20
        if latest['close'] > latest['Price_10d_MA']: svss_score += 30
        if latest['put_call_ratio_vol'] < 1.0: svss_score += 20
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("SVSS Score", f"{svss_score}/100", delta="High Risk" if svss_score > 70 else "Low Risk", delta_color="inverse" if svss_score > 70 else "normal")
        c2.metric("Short Vol vs 30d MA", f"{latest['ShortVolPct']*100:.1f}%", f"{(latest['ShortVolPct'] - latest['ShortVolPct_30d_MA'])*100:+.1f}%")
        c3.metric("Price vs 10d MA", f"${latest['close']:.2f}", f"${(latest['close'] - latest['Price_10d_MA']):+.2f}")
        
        # Display MM Hedging Divergence if true
        if latest['MM_Hedging_Flag']:
            c4.metric("Positioning Indicator", "MM Hedging (Bullish)", delta="Divergence Detected", delta_color="normal")
        else:
            c4.metric("Positioning Indicator", "Directional", delta="Standard", delta_color="off")

        # DataFrame restricted to last 90 days for plotting Models
        df_90d = merged_df.tail(90).copy()

        # ==========================================
        # MODEL 2: OPTIONS DIVERGENCE INDICATOR (ODI)
        # ==========================================
        st.divider()
        st.subheader("⚖️ Model 2: Options Divergence Indicator (ODI)")
        st.markdown("Compares off-exchange shorting against options market sentiment over the last 90 days. Divergences can signal market maker hedging or 'dumb money' being trapped.")
        
        from plotly.subplots import make_subplots
        
        fig_odi = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3], specs=[[{"secondary_y": True}], [{"secondary_y": False}]])
        
        fig_odi.add_trace(go.Scatter(x=df_90d['Date'], y=df_90d['ShortVolPct_10d_MA'], name='10d MA Short Vol %', line=dict(color='#EF553B', width=2)), row=1, col=1, secondary_y=False)
        fig_odi.add_trace(go.Scatter(x=df_90d['Date'], y=df_90d['PCR_10d_MA'], name='10d MA P/C Ratio', line=dict(color='#00CC96', width=2)), row=1, col=1, secondary_y=True)
        
        fig_odi.add_trace(go.Scatter(x=df_90d['Date'], y=df_90d['close'], name='Spot Price', line=dict(color='white', width=2)), row=2, col=1)
        
        fig_odi.update_layout(
            template='plotly_dark',
            hovermode='x unified',
            height=500,
            margin=dict(t=30, b=30, l=10, r=10),
            legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center")
        )
        fig_odi.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]), # hide weekends
                dict(values=MARKET_HOLIDAYS) # hide holidays
            ]
        )
        fig_odi.update_yaxes(title_text="Short Volume %", tickformat='.1%', secondary_y=False, row=1, col=1)
        fig_odi.update_yaxes(title_text="Put/Call Ratio", secondary_y=True, row=1, col=1)
        fig_odi.update_yaxes(title_text="Spot Price", row=2, col=1)
        
        st.plotly_chart(fig_odi, use_container_width=True)

        # ==========================================
        # MODEL 3A: CAPITULATION Z-SCORE
        # ==========================================
        st.divider()
        st.subheader("📊 Model 3A: Capitulation Z-Score")
        st.markdown("Identifies statistical extremes in short selling over the last 90 days. A massive spike > 2.5 SDs is often the final wave of selling (capitulation) before a reversal.")
        
        fig_z = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig_z.add_trace(go.Bar(
            x=df_90d['Date'], 
            y=df_90d['Z_Score'], 
            name='Daily Z-Score',
            marker_color=np.where(df_90d['Z_Score'] > 2.5, '#EF553B', np.where(df_90d['Z_Score'] < -2.5, '#00CC96', '#636EFA'))
        ), secondary_y=False)
        
        fig_z.add_trace(go.Scatter(
            x=df_90d['Date'], 
            y=df_90d['close'], 
            name='Spot Price',
            line=dict(color='white', width=2)
        ), secondary_y=True)
        
        fig_z.add_hline(y=2.5, line_dash="dash", line_color="#EF553B", annotation_text="+2.5 SD", secondary_y=False)
        fig_z.add_hline(y=-2.5, line_dash="dash", line_color="#00CC96", annotation_text="-2.5 SD", secondary_y=False)
        
        fig_z.update_layout(
            template='plotly_dark',
            hovermode='x unified',
            height=350,
            margin=dict(t=30, b=30, l=10, r=10),
            legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center")
        )
        fig_z.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),
                dict(values=MARKET_HOLIDAYS)
            ]
        )
        fig_z.update_yaxes(title_text="Z-Score (90d window)", secondary_y=False)
        fig_z.update_yaxes(title_text="Spot Price", secondary_y=True)
        st.plotly_chart(fig_z, use_container_width=True)

        # ==========================================
        # MODEL 3B: Z-SCORE EXHAUSTION & MOMENTUM
        # ==========================================
        st.subheader("⏱️ Model 3B: Short Selling Momentum")
        st.markdown("Tracks the *momentum* of the short selling Z-Score. \n- **MACD Lines**: When the Fast (Yellow) line crosses below the Slow (Purple) line, short selling momentum is fading.")
        
        fig_z2 = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Add Z-Score MACD lines
        fig_z2.add_trace(go.Scatter(x=df_90d['Date'], y=df_90d['Z_Score_EMA5'], name='Z-Score Fast (5d)', line=dict(color='yellow', width=2)), secondary_y=False)
        fig_z2.add_trace(go.Scatter(x=df_90d['Date'], y=df_90d['Z_Score_EMA10'], name='Z-Score Slow (10d)', line=dict(color='purple', width=2)), secondary_y=False)
        
        fig_z2.add_trace(go.Scatter(
            x=df_90d['Date'], 
            y=df_90d['close'], 
            name='Spot Price',
            line=dict(color='white', width=2, dash='dot')
        ), secondary_y=True)
        
        fig_z2.update_layout(
            template='plotly_dark',
            hovermode='x unified',
            height=350,
            margin=dict(t=30, b=30, l=10, r=10),
            legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center")
        )
        fig_z2.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),
                dict(values=MARKET_HOLIDAYS)
            ]
        )
        fig_z2.update_yaxes(title_text="Z-Score Momentum", secondary_y=False)
        fig_z2.update_yaxes(title_text="Spot Price", secondary_y=True)
        st.plotly_chart(fig_z2, use_container_width=True)

        # ==========================================
        # MODEL 4: GAMMA-AMPLIFIED SQUEEZE RISK
        # ==========================================
        st.divider()
        st.subheader("💥 Model 4: Gamma-Amplified Squeeze Risk")
        st.markdown("Short covering has an amplified impact when Market Makers are in **Negative Gamma** territory. Points are colored by their **T+5 Return**.")
        
        # Filter for the last 60 days to make the scatter plot relevant to recent action
        recent_df = merged_df.tail(60).dropna(subset=['net_gamma', 'ShortVolPct']).copy()
        
        if not recent_df.empty:
            fig_scatter = go.Figure()
            
            # Add quadrants
            avg_short = recent_df['ShortVolPct'].mean()
            
            fig_scatter.add_vline(x=avg_short, line_dash="dash", line_color="white", opacity=0.3)
            fig_scatter.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
            
            # Format returns for hover text (some might be NaN for the last few days)
            def format_hover(row):
                d = row['Date'].strftime('%Y-%m-%d')
                s = f"{row['ShortVolPct']:.1%}"
                g = f"{row['net_gamma']:,.0f}"
                t3 = f"{row.get('t+3_return', 0):+.2%}" if not pd.isna(row.get('t+3_return')) else "N/A"
                t5 = f"{row.get('t+5_return', 0):+.2%}" if not pd.isna(row.get('t+5_return')) else "N/A"
                t10 = f"{row.get('t+10_return', 0):+.2%}" if not pd.isna(row.get('t+10_return')) else "N/A"
                return f"<b>Date:</b> {d}<br><b>Short Vol:</b> {s}<br><b>Net Gamma:</b> {g}<br><br><b>T+3 Return:</b> {t3}<br><b>T+5 Return:</b> {t5}<br><b>T+10 Return:</b> {t10}"
            
            recent_df['hover_text'] = recent_df.apply(format_hover, axis=1)
            
            fig_scatter.add_trace(go.Scatter(
                x=recent_df['ShortVolPct'], 
                y=recent_df['net_gamma'],
                mode='markers',
                marker=dict(
                    size=12,
                    color=recent_df['t+5_return'].fillna(0),
                    colorscale=[[0, '#EF553B'], [0.5, '#636EFA'], [1, '#00CC96']], # Red -> Blue -> Green
                    cmid=0, # Center color scale on 0 return
                    showscale=True,
                    colorbar=dict(title="T+5 Return", tickformat='.1%'),
                    line=dict(color='white', width=1)
                ),
                text=recent_df['hover_text'],
                hovertemplate="%{text}<extra></extra>"
            ))
            
            # Highlight latest point
            if not pd.isna(latest['net_gamma']):
                fig_scatter.add_trace(go.Scatter(
                    x=[latest['ShortVolPct']],
                    y=[latest['net_gamma']],
                    mode='markers',
                    marker=dict(size=18, color='yellow', symbol='star'),
                    name='Latest Day',
                    hovertemplate="<b>Latest Day</b><extra></extra>"
                ))
            
            fig_scatter.add_annotation(x=recent_df['ShortVolPct'].max(), y=min(0, recent_df['net_gamma'].min()), text="🚨 DANGER ZONE 🚨", showarrow=False, font=dict(color="#EF553B", size=14))
            
            fig_scatter.update_layout(
                template='plotly_dark',
                xaxis_title="Short Volume %",
                xaxis_tickformat='.1%',
                yaxis_title="Total Net Gamma Exposure",
                height=500,
                showlegend=False,
                margin=dict(t=30, b=30, l=10, r=10)
            )
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.info("Insufficient options gamma data to calculate the Gamma-Amplified Squeeze Risk.")

        # ==========================================
        # MODEL 5: 5-DAY BUY RATIO & HIDDEN ACCUMULATION
        # ==========================================
        st.divider()
        st.subheader("📈 Model 5: 5-Day Buy Ratio & Hidden Accumulation")
        st.markdown("Compares the rolling 5-day implied long volume to short volume. A ratio > 1 implies net buying. Spikes on red days highlight hidden institutional accumulation.")
        
        fig_buy = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Color bars green if accumulation (Buy_Ratio_5d > Buy_Ratio_30d_MA), red if distribution
        colors = np.where(df_90d['Buy_Ratio_5d'] > df_90d['Buy_Ratio_30d_MA'], '#00CC96', '#EF553B')
        
        fig_buy.add_trace(go.Bar(
            x=df_90d['Date'], 
            y=df_90d['Buy_Ratio_5d'], 
            name='5-Day Buy Ratio',
            marker_color=colors
        ), secondary_y=False)
        
        fig_buy.add_trace(go.Scatter(
            x=df_90d['Date'], 
            y=df_90d['Buy_Ratio_30d_MA'], 
            name='30-Day Avg Ratio',
            line=dict(color='yellow', width=2, dash='dot')
        ), secondary_y=False)
        
        fig_buy.add_trace(go.Scatter(
            x=df_90d['Date'], 
            y=df_90d['close'], 
            name='Spot Price',
            line=dict(color='white', width=2)
        ), secondary_y=True)
        
        fig_buy.add_hline(y=1.0, line_dash="dash", line_color="white", annotation_text="Net Neutral (1.0)", secondary_y=False)
        
        fig_buy.update_layout(
            template='plotly_dark',
            hovermode='x unified',
            height=400,
            margin=dict(t=30, b=30, l=10, r=10),
            legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center")
        )
        fig_buy.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]), # hide weekends
                dict(values=MARKET_HOLIDAYS) # hide holidays
            ]
        )
        fig_buy.update_yaxes(title_text="Buy / Short Ratio", secondary_y=False)
        fig_buy.update_yaxes(title_text="Spot Price", secondary_y=True)
        st.plotly_chart(fig_buy, use_container_width=True)
