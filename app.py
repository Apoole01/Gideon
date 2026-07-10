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
    months = sorted(list(set([e[:7] for e in available_exps])))
    saved_m = st.session_state.saved_months.get(unique_id)

    col_m, col_e = st.columns([1, 2])
    with col_m:
        if is_multi:
            saved_m = saved_m if isinstance(saved_m, list) else []
            valid_m_defaults = [m for m in saved_m if m in months]
            if not valid_m_defaults and months: valid_m_defaults = [months[0]]
            sel_m = st.multiselect("Filter by Month(s):", months, default=valid_m_defaults,
                                   format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'), key=f"m_{unique_id}")
        else:
            m_index = months.index(saved_m) if saved_m in months else 0
            sel_m = st.selectbox("Filter by Month:", months, index=m_index,
                                 format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'), key=f"m_{unique_id}")
        st.session_state.saved_months[unique_id] = sel_m

    filtered_exps = [e for e in available_exps if any(e.startswith(m) for m in sel_m)] if is_multi else [e for e in
                                                                                                         available_exps
                                                                                                         if
                                                                                                         e.startswith(
                                                                                                             sel_m)]

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
            sel_e = st.selectbox("Select Expiration:", filtered_exps, index=e_index, format_func=get_exp_label,
                                 key=f"e_{unique_id}")
            st.session_state.saved_exps[unique_id] = sel_e
            return sel_e


# --- DATA CONNECTION & CACHING ---
@st.cache_data(ttl=3600)
def load_s3_data():
    load_dotenv()
    aws_key = os.getenv('AWS_ACCESS_KEY')
    aws_secret = os.getenv('AWS_SECRET_KEY')
    bucket_name = os.getenv('S3_BUCKET_NAME')

    if not aws_key or not aws_secret:
        st.error("Critical Error: AWS credentials not found. Check your .env file.")
        return pd.DataFrame(), pd.DataFrame()

    con = duckdb.connect(':memory:')
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
    con.execute(f"CREATE SECRET (TYPE S3, KEY_ID '{aws_key}', SECRET '{aws_secret}', REGION 'us-east-2');")

    try:
        df_summary = con.execute(
            f"SELECT * FROM read_parquet('s3://{bucket_name}/dashboard_data/ticker_summary_gold.parquet') WHERE strftime(date, '%Y-%m-%d') NOT IN {tuple(MARKET_HOLIDAYS)} ORDER BY date ASC").df()
        df_chain = con.execute(
            f"SELECT * FROM read_parquet('s3://{bucket_name}/dashboard_data/enriched_chain_gold.parquet') WHERE strftime(timestamp, '%Y-%m-%d') NOT IN {tuple(MARKET_HOLIDAYS)} ORDER BY timestamp ASC").df()
        return df_summary, df_chain
    except Exception as e:
        st.error(f"Error connecting to S3: {e}")
        return pd.DataFrame(), pd.DataFrame()


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


# --- LOAD DATA ---
df_summary, df_chain = load_s3_data()
if df_summary.empty or df_chain.empty: st.stop()

# --- GLOBALS & SIDEBAR ---
st.sidebar.title("Radar Controls")
selected_ticker = st.sidebar.selectbox("Select Asset:", df_summary['ticker'].unique())
st.sidebar.divider()
global_timeframe = st.sidebar.radio("Global Trend Scope:",
                                    ["20 Days (Daily)", "60 Days (Weekly)", "180 Days (Weekly)", "360 Days (Monthly)"])
st.sidebar.divider()

# --- MEGA PRE-COMPUTATION (SPEED FIX) ---
ticker_summary = df_summary[df_summary['ticker'] == selected_ticker].copy()
ticker_summary['date_str'] = ticker_summary['date'].astype(str).str[:10]

ticker_chain = df_chain[df_chain['ticker'] == selected_ticker].copy()
ticker_chain['date_str'] = ticker_chain['timestamp'].astype(str).str[:10]
ticker_chain['date_dt'] = pd.to_datetime(ticker_chain['date_str'])
ticker_chain['exp_dt'] = pd.to_datetime(ticker_chain['expiration'])
ticker_chain['dte'] = (ticker_chain['exp_dt'] - ticker_chain['date_dt']).dt.days

ticker_chain['underlying_price'] = pd.to_numeric(ticker_chain['underlying_price'], errors='coerce')
ticker_chain['last_price'] = pd.to_numeric(ticker_chain['last_price'], errors='coerce').fillna(0)
ticker_chain['volume'] = pd.to_numeric(ticker_chain['volume'], errors='coerce').fillna(0)
ticker_chain['open_interest'] = pd.to_numeric(ticker_chain['open_interest'], errors='coerce').fillna(0)
ticker_chain['iv'] = pd.to_numeric(ticker_chain['iv'], errors='coerce')
ticker_chain['delta'] = pd.to_numeric(ticker_chain['delta'], errors='coerce')

# Premium tracking
ticker_chain['premium_vol'] = ticker_chain['volume'] * ticker_chain['last_price'] * 100
ticker_chain['premium_oi'] = ticker_chain['open_interest'] * ticker_chain['last_price'] * 100

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
tab1, tab2, tab3, tab_sector, tab_stealth, tab_signals, tab_heatmap = st.tabs(
    ["🌊 Positioning", "📈 Volatility", "📍 Gamma/Delta", "⚖️ Sector Rotation", "🕵️ Accumulation", "🎯 Signals", "🌡️ Surface Heatmap"]
)

# ==========================================
# TAB 1: POSITIONING
# ==========================================
with tab1:
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

        fig_vol.update_layout(title="Volume Stack & P/C Ratio", template='plotly_dark', barmode='stack',
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
            df_chg = df_chg[df_chg['expiration'] == sel_oi_exp]
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
            hist_df = ticker_chain[
                (ticker_chain['expiration'] == sel_hist_exp) & (ticker_chain['date_str'] <= selected_date)].copy()

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
            df_pie = df_pie[df_pie['expiration'] == sel_pie_exp]
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
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.subheader("VWKS Trend (Center of Mass)")
        c_vw_r, c_vw_s = st.columns([2, 1])
        with c_vw_r:
            vwks_scope = st.radio("VWKS Scope:",
                                  ["All Exps", "Front-Month (7-45 DTE)", "Long-Term (>45 DTE)", "Specific Expiration"],
                                  horizontal=True, label_visibility="collapsed", key="vwks_radio")
        with c_vw_s:
            sel_vwks_exp = render_two_step_selector("vwks_exp", sorted(t_chain['expiration'].dropna().unique()),
                                                    is_multi=False) if vwks_scope == "Specific Expiration" else None

        if not t_chain.empty:
            df_vw = t_chain.copy()
            if vwks_scope == "Specific Expiration" and sel_vwks_exp:
                df_vw = df_vw[df_vw['expiration'] == sel_vwks_exp]
            elif "Front-Month" in vwks_scope:
                df_vw = df_vw[(df_vw['dte'] >= 7) & (df_vw['dte'] <= 45)]
            elif "Long-Term" in vwks_scope:
                df_vw = df_vw[df_vw['dte'] > 45]

            df_vw = df_vw[df_vw['underlying_price'] > 0]
            if not df_vw.empty:
                df_vw['vwks_num'] = ((df_vw['strike'] / df_vw['underlying_price']) - 1) * df_vw['volume']
                vwks_agg = df_vw.groupby('plot_date').agg(num=('vwks_num', 'sum'), den=('volume', 'sum')).reset_index()
                vwks_agg['vwks'] = (vwks_agg['num'] / vwks_agg['den']) * 100
                fig_vwks = px.line(vwks_agg, x='plot_date', y='vwks', markers=True, template='plotly_dark')
                fig_vwks.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5)
                fig_vwks.update_layout(xaxis_title=None, yaxis_title="VWKS (%)", margin=dict(t=30, b=10, l=10, r=10),
                                       xaxis=dict(type='category', categoryorder='category ascending'))
                st.plotly_chart(fig_vwks, use_container_width=True)

    with col_m2:
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
                if selected_sp_exp: sp_df = sp_df[sp_df['expiration'] == selected_sp_exp].copy()
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
with tab2:
    st.subheader("Omni-Volatility Dynamics (Filtered Scope)")
    c_mode, c_bar, c_exp, c_togg = st.columns([1.5, 1.2, 1, 1])
    with c_mode:
        iv_scope = st.radio("Trend Scope:", ["Front-Month (7-45 DTE)", "Specific Expiration"], horizontal=True,
                            label_visibility="collapsed")
    with c_bar:
        bar_mode = st.radio("Background Bars:", ["Volume (Flow)", "Open Interest (Structure)"], horizontal=True,
                            label_visibility="collapsed")
    with c_exp:
        selected_iv_exp = render_two_step_selector("iv_trend", sorted(ticker_chain['expiration'].dropna().unique()),
                                                   is_multi=False) if iv_scope == "Specific Expiration" else None
    with c_togg:
        # NEW: Toggle for <10 Delta wings
        show_10_delta = st.checkbox("Show <10Δ Wings", value=True)

    omni_data, prev_call_oi, prev_put_oi = [], None, None
    for d in ts_20d['date_str'].unique():
        day_df = ticker_chain[ticker_chain['date_str'] == d].copy()
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

        call_vol, put_vol = valid_df[valid_df['side'] == 'CALL']['volume'].sum(), valid_df[valid_df['side'] == 'PUT'][
            'volume'].sum()
        call_oi, put_oi = valid_df[valid_df['side'] == 'CALL']['open_interest'].sum(), \
        valid_df[valid_df['side'] == 'PUT']['open_interest'].sum()
        total_vol, total_oi = call_vol + put_vol, call_oi + put_oi

        c_pct = f"{(call_vol / total_vol * 100):.0f}%" if bar_mode == "Volume (Flow)" and total_vol > 0 else (
            f"{(call_oi / total_oi * 100):.0f}%" if total_oi > 0 else "")
        p_pct = f"{(put_vol / total_vol * 100):.0f}%" if bar_mode == "Volume (Flow)" and total_vol > 0 else (
            f"{(put_oi / total_oi * 100):.0f}%" if total_oi > 0 else "")

        c_delta_str = f"ΔOI: {(call_oi - prev_call_oi):+,.0f}" if prev_call_oi is not None and (
                    call_oi - prev_call_oi) != 0 else ""
        p_delta_str = f"ΔOI: {(put_oi - prev_put_oi):+,.0f}" if prev_put_oi is not None and (
                    put_oi - prev_put_oi) != 0 else ""
        prev_call_oi, prev_put_oi = call_oi, put_oi

        valid_df['strike_dist'] = (valid_df['strike'] - spot).abs()
        atm_iv = valid_df[valid_df['strike'] == valid_df.loc[valid_df['strike_dist'].idxmin(), 'strike']][
            'iv'].mean() if not valid_df['strike_dist'].isna().all() else np.nan

        calls, puts = valid_df[valid_df['side'] == 'CALL'], valid_df[valid_df['side'] == 'PUT']
        d25_c_iv = calls[(calls['delta'] >= 0.20) & (calls['delta'] <= 0.30)]['iv'].mean()
        d25_p_iv = puts[(puts['delta'] <= -0.20) & (puts['delta'] >= -0.30)]['iv'].mean()
        d10_c_iv = calls[(calls['delta'] > 0) & (calls['delta'] <= 0.10)]['iv'].mean()
        d10_p_iv = puts[(puts['delta'] < 0) & (puts['delta'] >= -0.10)]['iv'].mean()
        weighted_iv = np.average(valid_df['iv'], weights=valid_df['open_interest']) if valid_df[
                                                                                           'open_interest'].sum() > 0 else np.nan

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

        fig_omni.add_trace(
            go.Bar(x=omni_df['date_str'], y=omni_df[y_call], name=f'Call {bar_mode.split()[0]}', marker_color='#00CC96',
                   opacity=0.3, yaxis='y1', text=omni_df['Call Pct Text'], textposition='inside'))
        fig_omni.add_trace(
            go.Bar(x=omni_df['date_str'], y=omni_df[y_put], name=f'Put {bar_mode.split()[0]}', marker_color='#EF553B',
                   opacity=0.3, yaxis='y1', text=omni_df['Put Pct Text'], textposition='inside'))

        # Apply Toggle for 10 Delta
        if show_10_delta:
            fig_omni.add_trace(
                go.Scatter(x=omni_df['date_str'], y=omni_df['10Δ Call'], name='<10Δ Call IV', mode='lines',
                           line=dict(color='#00FF99', width=1, dash='dashdot'), yaxis='y2', opacity=0.6))
            fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['10Δ Put'], name='<10Δ Put IV', mode='lines',
                                          line=dict(color='#FF3366', width=1, dash='dashdot'), yaxis='y2', opacity=0.6))

        fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['25Δ Call'], name='25Δ Call IV', mode='lines',
                                      line=dict(color='#00664A', width=2, dash='dot'), yaxis='y2'))
        fig_omni.add_trace(go.Scatter(x=omni_df['date_str'], y=omni_df['25Δ Put'], name='25Δ Put IV', mode='lines',
                                      line=dict(color='#8B2211', width=2, dash='dot'), yaxis='y2'))
        fig_omni.add_trace(
            go.Scatter(x=omni_df['date_str'], y=omni_df['ATM IV'], name='ATM IV (Baseline)', mode='lines+markers',
                       line=dict(color='#FFFFFF', width=3), yaxis='y2'))
        fig_omni.add_trace(
            go.Scatter(x=omni_df['date_str'], y=omni_df['Weighted IV'], name='OI-Weighted IV', mode='lines+markers',
                       line=dict(color='#FECB52', width=4), yaxis='y2'))

        fig_omni.update_layout(template='plotly_dark', barmode='stack', height=600, hovermode='x unified',
                               yaxis=dict(title=y_axis_title, side='left', showgrid=False),
                               yaxis2=dict(title='Implied Volatility (%)', side='right', overlaying='y', showgrid=True),
                               legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"), margin=dict(b=80))
        fig_omni.update_xaxes(type='category', categoryorder='category ascending')
        st.plotly_chart(fig_omni, use_container_width=True)

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
with tab3:
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
        chain_gex = chain_gex[chain_gex['expiration'] == sel_gamma_exp]
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
        chain_dex = chain_dex[chain_dex['expiration'] == sel_delta_exp]
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
# CACHED SECTOR ROTATION ENGINE
# ==========================================
@st.cache_data(ttl=3600)
def compute_rotation_scores(df, comp_date):
    """Compute composite rotation scores for all 16 sector ETFs."""
    tickers = list(SECTOR_MAP.keys())
    sec = df[df['ticker'].isin(tickers)].copy()
    if sec.empty: return pd.DataFrame()

    sec['timestamp_dt'] = pd.to_datetime(sec['timestamp'])
    sec = sec[sec['timestamp_dt'].dt.weekday < 5].copy()
    sec['date_str'] = sec['timestamp_dt'].dt.strftime('%Y-%m-%d')
    sec['date_dt'] = pd.to_datetime(sec['date_str'])
    sec['exp_dt'] = pd.to_datetime(sec['expiration'])
    sec['dte'] = (sec['exp_dt'] - sec['date_dt']).dt.days
    sec['underlying_price'] = pd.to_numeric(sec['underlying_price'], errors='coerce')
    sec['volume'] = pd.to_numeric(sec['volume'], errors='coerce').fillna(0)
    sec['last_price'] = pd.to_numeric(sec['last_price'], errors='coerce').fillna(0)
    sec['iv'] = pd.to_numeric(sec['iv'], errors='coerce')
    sec['delta'] = pd.to_numeric(sec['delta'], errors='coerce')
    sec['premium'] = sec['volume'] * sec['last_price'] * 100

    # Get SPY prices from yfinance (single ticker, fast)
    try:
        spy_data = yf.download('SPY', start='2026-01-01', end=comp_date, progress=False)
        spy = spy_data[('Close', 'SPY')].dropna() if not spy_data.empty else pd.Series()
    except:
        spy = pd.Series()
    if spy.empty: return pd.DataFrame()

    # Use S3 chain underlying_price for sector ETFs (no network call needed)
    prices = {}
    for t in tickers:
        t_px = df[(df['ticker'] == t) & (df['timestamp'] < comp_date)].drop_duplicates(subset=['timestamp'])
        if not t_px.empty:
            t_px = t_px.sort_values('timestamp')
            t_px['date_dt'] = pd.to_datetime(t_px['timestamp']).dt.date
            prices[t] = t_px.set_index('date_dt')['underlying_price'].dropna()
    prices['SPY'] = spy

    # Front-month chain
    fm = sec[sec['dte'].between(7, 45)]
    if fm.empty: return pd.DataFrame()

    # Daily skew per ticker
    calls_25 = fm[(fm['side'] == 'CALL') & (fm['delta'].between(0.2, 0.3))].groupby(['ticker', 'date_str'])['iv'].mean()
    puts_25 = fm[(fm['side'] == 'PUT') & (fm['delta'].between(-0.3, -0.2))].groupby(['ticker', 'date_str'])['iv'].mean()
    skew_raw = ((puts_25 - calls_25) * 100).dropna().reset_index()
    skew_raw.columns = ['ticker', 'date_str', 'skew']

    # Daily premium per ticker
    prem_call = fm[fm['side'] == 'CALL'].groupby(['ticker', 'date_str'])['premium'].sum()
    prem_put = fm[fm['side'] == 'PUT'].groupby(['ticker', 'date_str'])['premium'].sum()
    prem_net = (prem_call - prem_put).dropna().reset_index()
    prem_net.columns = ['ticker', 'date_str', 'net_prem']

    # Aggregate to latest date for each ticker + compute across available history for each
    rows = []
    latest_dates = sec['date_str'].unique()
    # Use last 60 trading days
    lookback_dates = sorted(latest_dates)[-60:] if len(latest_dates) >= 60 else sorted(latest_dates)

    for t in tickers:
        if t not in prices or spy.empty: continue
        px = prices[t]
        common = px.index.intersection(spy.index)
        if len(common) < 20: continue
        px_a = px[common]; spy_a = spy[common]

        # Price RS (10d and 20d)
        rel_10d = ((px_a/px_a.shift(10)-1) - (spy_a/spy_a.shift(10)-1)).dropna()
        rel_20d = ((px_a/px_a.shift(20)-1) - (spy_a/spy_a.shift(20)-1)).dropna()
        rs_momentum = (rel_10d - rel_10d.shift(5)).dropna()

        latest_rel_10d = rel_10d.iloc[-1] * 100 if len(rel_10d) > 0 else 0
        latest_rel_20d = rel_20d.iloc[-1] * 100 if len(rel_20d) > 0 else 0
        latest_rs_mom = rs_momentum.iloc[-1] * 100 if len(rs_momentum) > 0 else 0

        # Options metrics for this ticker
        t_skew = skew_raw[skew_raw['ticker'] == t].sort_values('date_str')
        t_prem = prem_net[prem_net['ticker'] == t].sort_values('date_str')

        if t_skew.empty: continue

        skew_latest = t_skew['skew'].iloc[-1]
        skew_vals = t_skew['skew'].dropna()
        skew_pct = (skew_vals.iloc[-20:] < skew_latest).mean() * 100 if len(skew_vals) >= 20 else 50
        skew_momentum = skew_vals.iloc[-1] - skew_vals.iloc[-6] if len(skew_vals) >= 6 else 0

        # Premium flow
        prem_vals = t_prem['net_prem'].dropna()
        prem_5d = prem_vals.iloc[-5:].sum() if len(prem_vals) >= 5 else prem_vals.sum()
        prem_10d = prem_vals.iloc[-10:].sum() if len(prem_vals) >= 10 else prem_vals.sum()

        # Historical scores for timeline (last N periods)
        hist_scores = []
        for idx in range(max(0, len(t_skew)-30), len(t_skew)):
            d = t_skew['date_str'].iloc[idx]
            if d not in common: continue
            d_idx = common.get_loc(d) if d in common else -1
            if d_idx < 10: continue
            h_rel_10 = ((px_a.iloc[d_idx]/px_a.iloc[d_idx-10]-1) - (spy_a.iloc[d_idx]/spy_a.iloc[d_idx-10]-1)) * 100 if d_idx >= 10 else 0
            h_skew = t_skew['skew'].iloc[idx]
            h_prem = t_prem[t_prem['date_str'] <= d]['net_prem'].iloc[-10:].sum() if len(t_prem[t_prem['date_str'] <= d]) >= 10 else 0
            hist_scores.append({'date_str': d, 'ticker': t, 'rel_10d': h_rel_10, 'skew': h_skew, 'prem_10d': h_prem})

        rows.append({
            'ticker': t, 'name': SECTOR_MAP.get(t, t),
            'rel_10d': latest_rel_10d, 'rel_20d': latest_rel_20d, 'rs_momentum': latest_rs_mom,
            'skew_latest': skew_latest, 'skew_pct': skew_pct, 'skew_momentum': skew_momentum,
            'prem_5d': prem_5d, 'prem_10d': prem_10d, 'hist_scores': hist_scores
        })

    if len(rows) < 3: return pd.DataFrame()

    comp = pd.DataFrame(rows)

    # Z-score normalize across sectors
    for col in ['rel_10d', 'rs_momentum', 'prem_10d', 'skew_latest']:
        if col in comp.columns:
            v = comp[col].dropna()
            if len(v) > 1 and v.std() > 0:
                comp[f'{col}_z'] = ((comp[col] - v.mean()) / v.std()).clip(-2, 2) / 2

    # Composite: 30% RS + 25% skew + 30% flow + 15% momentum
    comp['score'] = 0.0
    w_sum = 0.0
    for col, w in [('rel_10d_z', 0.30), ('skew_latest_z', 0.25), ('prem_10d_z', 0.30), ('rs_momentum_z', 0.15)]:
        if col in comp.columns:
            comp['score'] += comp[col].fillna(0) * w
            w_sum += w
    if w_sum > 0: comp['score'] = (comp['score'] / w_sum) * 100

    # Zone classification
    def zone_label(s):
        if s > 60: return 'Extreme Overbought'
        if s > 20: return 'Overbought'
        if s > -20: return 'Neutral'
        if s > -60: return 'Oversold'
        return 'Deep Oversold'
    comp['zone'] = comp['score'].apply(zone_label)

    # Divergence detection
    comp['divergence'] = ''
    for i, r in comp.iterrows():
        rs_z = r.get('rel_10d_z', 0) or 0
        sk_z = r.get('skew_latest_z', 0) or 0
        if rs_z > 0.3 and sk_z < -0.2:
            comp.at[i, 'divergence'] = 'Bearish Div (Price up, Options fearful)'
        elif rs_z < -0.3 and sk_z > 0.2:
            comp.at[i, 'divergence'] = 'Bullish Div (Price down, Options greedy)'

    return comp.sort_values('score', ascending=False)


# ==========================================
# TAB 4: SECTOR ROTATION OSCILLATOR
# ==========================================
with tab_sector:
    st.header("Sector Rotation Oscillator")
    st.markdown("Composite score from price relative strength (30%), options skew (25%), premium flow (30%), and RS momentum (15%). **Overbought = rotation OUT likely. Oversold = rotation IN likely.**")

    with st.spinner("Computing rotation scores..."):
        rotation_df = compute_rotation_scores(df_chain, comp_date)

    if rotation_df.empty:
        st.warning("Insufficient data to compute rotation scores.")
    else:
        # ═══════════ ROW 1: ROTATION OSCILLATOR (HORIZONTAL BARS) ═══════════
        st.divider()
        c_osc, c_legend = st.columns([3, 1])
        with c_osc:
            st.subheader("Rotation Score — All 16 Sectors")

            fig_osc = go.Figure()

            # Color map by zone
            zone_colors = {
                'Extreme Overbought': '#00CC96',
                'Overbought': 'rgba(0,204,150,0.6)',
                'Neutral': 'rgba(254,203,82,0.5)',
                'Oversold': 'rgba(239,85,59,0.6)',
                'Deep Oversold': '#EF553B'
            }

            display_df = rotation_df.copy()
            colors = [zone_colors.get(z, '#888') for z in display_df['zone']]

            fig_osc.add_trace(go.Bar(
                y=display_df['name'], x=display_df['score'],
                orientation='h', marker_color=colors,
                text=[f"{s:+.0f}  " for s in display_df['score']],
                textposition='outside', textfont=dict(color='white', size=11),
                hovertemplate='%{y}: %{x:+.0f}<br>Zone: %{customdata}<br>RS 10d: %{text}%',
                customdata=display_df['zone'],
            ))

            # Zone lines
            for val, color, label in [(-60, 'rgba(239,85,59,0.4)', 'Deep Oversold'),
                                       (-20, 'rgba(239,85,59,0.25)', 'Oversold'),
                                       (20, 'rgba(0,204,150,0.25)', 'Overbought'),
                                       (60, 'rgba(0,204,150,0.4)', 'Extreme Overbought')]:
                fig_osc.add_vline(x=val, line_dash='dash', line_color=color, line_width=1,
                                  annotation_text=label if abs(val)==60 else None,
                                  annotation_position='top' if val > 0 else 'bottom')
            fig_osc.add_vline(x=0, line_color='white', line_width=1, opacity=0.4)

            # Divergence markers
            divs = display_df[display_df['divergence'] != '']
            for _, d in divs.iterrows():
                idx = list(display_df['name']).index(d['name'])
                symb = '⚠️' if 'Bearish' in d['divergence'] else '💡'
                fig_osc.add_annotation(y=d['name'], x=d['score'] + (8 if d['score'] >= 0 else -8),
                    text=symb, showarrow=False, font=dict(size=14))

            fig_osc.update_layout(
                template='plotly_dark', height=500, margin=dict(l=10, r=60, t=10, b=10),
                xaxis=dict(title='Rotation Score (-100 to +100)', range=[-100, 100], showgrid=True, gridcolor='rgba(255,255,255,0.08)'),
                yaxis=dict(autorange='reversed', showgrid=False),
                showlegend=False, hovermode='y unified'
            )
            st.plotly_chart(fig_osc, use_container_width=True)

        with c_legend:
            st.markdown("**Zone Key**")
            st.markdown("🟢 **+60 to +100** Extreme Overbought — Rotation OUT")
            st.markdown("🟢 **+20 to +60** Overbought")
            st.markdown("🟡 **-20 to +20** Neutral — No signal")
            st.markdown("🔴 **-60 to -20** Oversold")
            st.markdown("🔴 **-100 to -60** Deep Oversold — Rotation IN")
            st.divider()
            st.markdown("**Divergence Markers**")
            st.markdown("⚠️ = Bearish Divergence (price up but options fearful)")
            st.markdown("💡 = Bullish Divergence (price down but options greedy)")
            st.divider()
            # Top/bottom summary
            top3 = rotation_df.head(3)
            bot3 = rotation_df.tail(3)
            st.metric("Most Overbought", top3['name'].iloc[0], f"{top3['score'].iloc[0]:+.0f}")
            if len(top3) > 1:
                st.caption(f"2. {top3['name'].iloc[1]} ({top3['score'].iloc[1]:+.0f})")
                st.caption(f"3. {top3['name'].iloc[2]} ({top3['score'].iloc[2]:+.0f})")
            st.divider()
            st.metric("Most Oversold", bot3['name'].iloc[-1], f"{bot3['score'].iloc[-1]:+.0f}")
            if len(bot3) > 1:
                st.caption(f"2. {bot3['name'].iloc[-2]} ({bot3['score'].iloc[-2]:+.0f})")
                st.caption(f"3. {bot3['name'].iloc[-3]} ({bot3['score'].iloc[-3]:+.0f})")

        # ═══════════ ROW 2: FLOW vs SKEW MATRIX (SCATTER) ═══════════
        st.divider()
        st.subheader("Flow vs Skew — Divergence Matrix")
        c_scat, c_scat_desc = st.columns([2.5, 1])

        with c_scat:
            fig_mat = go.Figure()

            for _, r in rotation_df.iterrows():
                sz = max(15, min(40, abs(r['prem_10d']) / max(1, abs(rotation_df['prem_10d']).mean()) * 20))
                color = zone_colors.get(r['zone'], '#888')

                fig_mat.add_trace(go.Scatter(
                    x=[r['skew_latest']], y=[r['rel_10d']],
                    mode='markers+text', name=r['name'],
                    marker=dict(size=sz, color=color, line=dict(color='white', width=1)),
                    text=r['ticker'], textposition='top center', textfont=dict(size=9, color='white'),
                    hovertemplate=f"{r['name']}<br>Skew: {r['skew_latest']:+.1f}<br>RS 10d: {r['rel_10d']:+.1f}%<br>Score: {r['score']:+.0f}"
                ))

            fig_mat.add_hline(y=0, line_color='white', line_width=1, opacity=0.3)
            fig_mat.add_vline(x=0, line_color='white', line_width=1, opacity=0.3)

            # Quadrant labels
            fig_mat.add_annotation(x=15, y=4, text='Bullish Flow<br>+ Price Leading', showarrow=False,
                font=dict(size=9, color='rgba(0,204,150,0.5)'))
            fig_mat.add_annotation(x=-15, y=4, text='Fear Premium<br>+ Price Leading', showarrow=False,
                font=dict(size=9, color='rgba(254,203,82,0.5)'))
            fig_mat.add_annotation(x=15, y=-4, text='Bullish Flow<br>+ Price Lagging', showarrow=False,
                font=dict(size=9, color='rgba(254,203,82,0.5)'))
            fig_mat.add_annotation(x=-15, y=-4, text='Fear Premium<br>+ Price Lagging', showarrow=False,
                font=dict(size=9, color='rgba(239,85,59,0.5)'))

            fig_mat.update_layout(
                template='plotly_dark', height=450, margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(title='Put-Call Skew (positive = fear, negative = greed)', showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
                yaxis=dict(title='10-Day Relative Strength vs SPY (%)', showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
                showlegend=False, hovermode='closest'
            )
            st.plotly_chart(fig_mat, use_container_width=True)

        with c_scat_desc:
            st.info("**How to read this chart:**\n\n"
                "**X-axis (Skew):** Right = puts expensive (fear). Left = calls expensive (greed).\n\n"
                "**Y-axis (RS):** Up = outperforming SPY. Down = underperforming.\n\n"
                "**Bubble size** = premium flow magnitude.\n\n"
                "**Top-right = Strong & Loved** — momentum, but watch for exhaustion.\n"
                "**Bottom-left = Weak & Hated** — potential value if skew shows fear capitulation.\n"
                "**Top-left = Fear Premium + Price Leading** — divergence, institutions hedging a rally.\n"
                "**Bottom-right = Bullish Flow + Price Lagging** — divergence, smart money buying the dip.")

        # ═══════════ ROW 3: DIVERGENCE ALERTS ═══════════
        if len(divs) > 0:
            st.divider()
            st.subheader("Active Divergence Alerts")
            alert_cols = st.columns(min(len(divs), 4))
            for i, (_, d) in enumerate(divs.iterrows()):
                with alert_cols[i % 4]:
                    is_bear = 'Bearish' in d['divergence']
                    st.warning(f"**{d['name']} ({d['ticker']})**\n\n"
                        f"{d['divergence']}\n\n"
                        f"Score: {d['score']:+.0f} | RS 10d: {d['rel_10d']:+.1f}% | Skew: {d['skew_latest']:+.1f}")

        # ═══════════ ROW 4: SCORE BREAKDOWN TABLE ═══════════
        st.divider()
        st.subheader("Score Breakdown")
        breakdown = rotation_df[['ticker', 'name', 'score', 'zone', 'rel_10d', 'skew_latest', 'skew_pct', 'prem_10d', 'divergence']].copy()
        breakdown.columns = ['ETF', 'Sector', 'Score', 'Zone', 'RS 10d %', 'Skew', 'Skew %ile', 'Flow 10d $', 'Divergence']
        breakdown['Score'] = breakdown['Score'].apply(lambda x: f"{x:+.0f}")
        breakdown['RS 10d %'] = breakdown['RS 10d %'].apply(lambda x: f"{x:+.1f}")
        breakdown['Skew'] = breakdown['Skew'].apply(lambda x: f"{x:+.1f}")
        breakdown['Skew %ile'] = breakdown['Skew %ile'].apply(lambda x: f"{x:.0f}")
        breakdown['Flow 10d $'] = breakdown['Flow 10d $'].apply(lambda x: f"${x/1e6:+.1f}M" if abs(x) > 1e6 else f"${x/1e3:+.0f}K")

        def highlight_divergence(val):
            if 'Bearish' in str(val): return 'background-color: rgba(239,85,59,0.3); color: #EF553B'
            if 'Bullish' in str(val): return 'background-color: rgba(0,204,150,0.3); color: #00CC96'
            return ''

        try:
            styled = breakdown.style.applymap(highlight_divergence, subset=['Divergence'])
        except AttributeError:
            styled = breakdown.style.map(highlight_divergence, subset=['Divergence'])
        st.dataframe(styled, use_container_width=True, hide_index=True)

# ==========================================
# TAB 7: STEALTH ACCUMULATION VISUALIZER
# ==========================================
with tab_stealth:
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

                fig5.update_layout(title="5. Far-OTM (<10Δ) Call Delta Expansion", template='plotly_dark', height=350,
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
# TAB 7.5: BACKTESTED SIGNALS — FILTERED & RISK-MANAGED
# ==========================================
with tab_signals:
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
            agg_vwks_sig['spot_3d_ma'] = agg_vwks_sig['date_str'].map(spot_ma_sig)
            agg_vwks_sig['smooth_gap_pct'] = ((agg_vwks_sig['VWKS_3D_MA'] - agg_vwks_sig['spot_3d_ma']) / agg_vwks_sig['spot_3d_ma']) * 100

            # --- Compute Put VWKS ---
            df_put_sig = s_hist[(s_hist['side'] == 'PUT') & (s_hist['dte'].between(7, 45))].copy()
            df_put_sig['vwks_num_put'] = df_put_sig['strike'] * df_put_sig['volume']
            agg_put_sig = df_put_sig.groupby('date_str').apply(lambda x: (x['vwks_num_put'].sum() / x['volume'].sum()) if x['volume'].sum() > 0 else np.nan).rename('VWKS_PUT').reset_index()
            agg_put_sig['VWKS_PUT_3D'] = agg_put_sig['VWKS_PUT'].rolling(3, min_periods=1).mean()

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
            call_exp_pivot = pd.DataFrame()
            put_exp_pivot = pd.DataFrame()
            net_exp_pivot = pd.DataFrame()
            exp_weeks = []

            if not far_call_sig.empty:
                far_call_sig['notional_delta'] = far_call_sig['delta'] * far_call_sig['open_interest'] * 100 * far_call_sig['underlying_price']
                far_call_sig['exp_dt'] = pd.to_datetime(far_call_sig['expiration'])
                far_call_sig['exp_week'] = far_call_sig['exp_dt'].dt.to_period('W-FRI').dt.end_time.dt.strftime('%b %d')
                agg_call_sig = far_call_sig.groupby('date_str')['notional_delta'].sum().reset_index()
                agg_call_sig['Delta_3D_MA'] = agg_call_sig['notional_delta'].rolling(3, min_periods=1).mean()
                # Pivot: date x expiration week
                call_exp_pivot = far_call_sig.groupby(['date_str','exp_week'])['notional_delta'].sum().unstack(fill_value=0)

            if not far_put_sig.empty:
                far_put_sig['notional_delta'] = far_put_sig['delta'].abs() * far_put_sig['open_interest'] * 100 * far_put_sig['underlying_price']
                far_put_sig['exp_dt'] = pd.to_datetime(far_put_sig['expiration'])
                far_put_sig['exp_week'] = far_put_sig['exp_dt'].dt.to_period('W-FRI').dt.end_time.dt.strftime('%b %d')
                agg_put_sig_otm = far_put_sig.groupby('date_str')['notional_delta'].sum().reset_index()
                agg_put_sig_otm['Delta_3D_MA'] = agg_put_sig_otm['notional_delta'].rolling(3, min_periods=1).mean()
                put_exp_pivot = far_put_sig.groupby(['date_str','exp_week'])['notional_delta'].sum().unstack(fill_value=0)

            # All expiration weeks — keep top 5 by total notional, rest become "Other"
            all_exp_weeks = sorted(list(set(list(call_exp_pivot.columns) if not call_exp_pivot.empty else []) | set(list(put_exp_pivot.columns) if not put_exp_pivot.empty else [])))
            # Rank by total contribution
            week_totals = {}
            if not call_exp_pivot.empty:
                for w in call_exp_pivot.columns: week_totals[w] = week_totals.get(w,0) + call_exp_pivot[w].sum()
            if not put_exp_pivot.empty:
                for w in put_exp_pivot.columns: week_totals[w] = week_totals.get(w,0) + put_exp_pivot[w].sum()
            top_weeks = sorted(week_totals, key=week_totals.get, reverse=True)[:5]
            other_weeks = [w for w in all_exp_weeks if w not in top_weeks]
            display_weeks = top_weeks + (['Other'] if other_weeks else [])
            exp_week_colors = ['#00CC96','#FECB52','#EF553B','#636EFA','#AB63FA','#888888']

            # Net notional delta (calls - puts) per expiration week
            if not far_call_sig.empty or not far_put_sig.empty:
                # Total net
                net = agg_call_sig[['date_str','notional_delta']].rename(columns={'notional_delta':'call_delta'}).merge(
                    agg_put_sig_otm[['date_str','notional_delta']].rename(columns={'notional_delta':'put_delta'}),
                    on='date_str', how='outer').fillna(0).sort_values('date_str')
                net['net_delta'] = net['call_delta'] - net['put_delta']
                net['Net_3D_MA'] = net['net_delta'].rolling(5, min_periods=2).mean()
                net['nd_rising'] = net['Net_3D_MA'] > net['Net_3D_MA'].shift(1)
                agg_net_sig = net
                # Net per expiration week (calls - puts)
                if not call_exp_pivot.empty or not put_exp_pivot.empty:
                    net_exp_pivot = call_exp_pivot.reindex(columns=all_exp_weeks, fill_value=0) - put_exp_pivot.reindex(columns=all_exp_weeks, fill_value=0)
                    net_exp_pivot = net_exp_pivot.reindex(sorted(net_exp_pivot.index), fill_value=0)

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

            # ==========================================
            # CHART 2: PUT VWKS DIVERGENCE (NEW)
            # ==========================================
            st.divider()
            c_put, c_put_desc = st.columns([2, 1])
            with c_put:
                fig_s2 = make_subplots(specs=[[{"secondary_y": True}]])

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

                # Spot price
                fig_s2.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s2.update_layout(title="2. Put VWKS Divergence — Dual Accumulation Check", template='plotly_dark',
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"))
                fig_s2.update_xaxes(type='category', categoryorder='category ascending')
                fig_s2.update_yaxes(title_text="Strike ($)", secondary_y=False)
                fig_s2.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s2, use_container_width=True)
            with c_put_desc:
                st.info("**NEW — Backtest Validated:** M7 (Call VWKS up + Put VWKS down) beats M1 by **6% hit rate**.\n\n"
                    "**Green line** = Call VWKS (volume-weighted strike for calls). **Red line** = Put VWKS (for puts).\n\n"
                    "**What to look for:** Green rising while red falling = genuine institutional accumulation. When both rise = hedging, not accumulation (M8 — ignore).\n\n"
                    "**Yellow diamonds** = M7 signal fires (Call up + Put down + spot not spiked). 56% historical hit rate at t10.")

            # ==========================================
            # CHART 3: BACKWARDATION MAGNITUDE MONITOR
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

                fig_s3.update_layout(title="3. Backwardation Magnitude — Tier Monitor", template='plotly_dark',
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
            # CHART 4: OTM DELTA — CALLS vs PUTS by Expiration Week (Top 5)
            # ==========================================
            st.divider()
            c_otm, c_otm_desc = st.columns([2, 1])
            with c_otm:
                fig_s4 = make_subplots(specs=[[{"secondary_y": True}]])

                # Merge other weeks into "Other" column for calls
                call_plot = call_exp_pivot.copy() if not call_exp_pivot.empty else pd.DataFrame()
                if not call_plot.empty and other_weeks:
                    call_plot['Other'] = call_plot[other_weeks].sum(axis=1) if all(w in call_plot.columns for w in other_weeks) else call_plot[[w for w in other_weeks if w in call_plot.columns]].sum(axis=1)
                call_plot = call_plot.reindex(sorted(call_plot.index), fill_value=0)

                # Merge other weeks into "Other" column for puts
                put_plot = put_exp_pivot.copy() if not put_exp_pivot.empty else pd.DataFrame()
                if not put_plot.empty and other_weeks:
                    put_plot['Other'] = put_plot[other_weeks].sum(axis=1) if all(w in put_plot.columns for w in other_weeks) else put_plot[[w for w in other_weeks if w in put_plot.columns]].sum(axis=1)
                put_plot = put_plot.reindex(sorted(put_plot.index), fill_value=0)

                # CALLS stacked (positive)
                if not call_plot.empty:
                    for wi, week in enumerate(display_weeks):
                        if week in call_plot.columns:
                            vals = call_plot[week]
                            if vals.sum() > 0:
                                color = exp_week_colors[wi % len(exp_week_colors)]
                                fig_s4.add_trace(go.Bar(x=call_plot.index, y=vals,
                                    name=f'Call {week}', marker_color=color, showlegend=True), secondary_y=False)

                # PUTS stacked (negative)
                if not put_plot.empty:
                    for wi, week in enumerate(display_weeks):
                        if week in put_plot.columns:
                            vals = -put_plot[week]
                            if abs(vals).sum() > 0:
                                color = exp_week_colors[wi % len(exp_week_colors)]
                                fig_s4.add_trace(go.Bar(x=put_plot.index, y=vals,
                                    name=f'Put {week}', marker_color=color, showlegend=True), secondary_y=False)

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

                fig_s4.update_layout(title="4. Far-OTM (<10Δ) Notional Delta — Top 5 Exp Weeks",
                    template='plotly_dark', barmode='relative', bargap=0,
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(size=9)))
                fig_s4.update_xaxes(type='category', categoryorder='category ascending')
                fig_s4.update_yaxes(title_text="Notional Delta ($)", secondary_y=False)
                fig_s4.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s4, use_container_width=True)
            with c_otm_desc:
                st.info("**Calls (above zero) vs Puts (below zero) — stacked by top 5 expiration weeks.**\n\n"
                    "Each color = different expiration week. Remaining weeks combined into grey 'Other'.\n\n"
                    "**White line** = zero split. **Yellow triangles** = M5 signal.")

            # ==========================================
            # CHART 5: NET NOTIONAL DELTA by Expiration Week (Top 5)
            # ==========================================
            st.divider()
            c_net, c_net_desc = st.columns([2, 1])
            with c_net:
                fig_s5 = make_subplots(specs=[[{"secondary_y": True}]])

                net_plot = net_exp_pivot.copy() if not net_exp_pivot.empty else pd.DataFrame()
                if not net_plot.empty and other_weeks:
                    avail_other = [w for w in other_weeks if w in net_plot.columns]
                    if avail_other:
                        net_plot['Other'] = net_plot[avail_other].sum(axis=1)
                net_plot = net_plot.reindex(sorted(net_plot.index), fill_value=0)

                if not net_plot.empty:
                    for wi, week in enumerate(display_weeks):
                        if week in net_plot.columns:
                            vals = net_plot[week]
                            if abs(vals).sum() > 0:
                                color = exp_week_colors[wi % len(exp_week_colors)]
                                fig_s5.add_trace(go.Bar(x=net_plot.index, y=vals,
                                    name=f'{week}', marker_color=color, showlegend=True), secondary_y=False)

                if not agg_net_sig.empty:
                    fig_s5.add_trace(go.Scatter(x=agg_net_sig['date_str'], y=agg_net_sig['Net_3D_MA'],
                        mode='lines', line=dict(color='#00CC96', width=2.5), name='Net 5D MA'), secondary_y=False)
                    fig_s5.add_hline(y=0, line_color='white', line_width=1, opacity=0.4, secondary_y=False)

                fig_s5.add_trace(go.Scatter(x=s_spot.index, y=s_spot.values, name="Spot Price", mode='lines',
                    line=dict(color='white', width=2, dash='dot')), secondary_y=True)

                fig_s5.update_layout(title="5. Net Far-OTM Notional Delta (Calls − Puts) by Exp Week",
                    template='plotly_dark', barmode='relative', bargap=0,
                    height=350, margin=dict(l=10, r=10, t=40, b=10), hovermode='x unified',
                    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(size=9)))
                fig_s5.update_xaxes(type='category', categoryorder='category ascending')
                fig_s5.update_yaxes(title_text="Net Notional Delta ($)", secondary_y=False)
                fig_s5.update_yaxes(showgrid=False, secondary_y=True)
                st.plotly_chart(fig_s5, use_container_width=True)
            with c_net_desc:
                st.info("**Net = Calls minus Puts, stacked by top 5 expiration weeks.**\n\n"
                    "Each color = different expiration week. Grey = all other weeks combined.\n\n"
                    "**Green line** = 5-day MA of total net delta. Above zero = net bullish, below = net bearish.")

            # ==========================================
            # SIGNAL LOG TABLE
            # ==========================================
            st.divider()
            st.subheader("📋 Recent Signal History")

            # Build signal log
            all_signal_dates = set()
            all_signal_dates.update(sig_m3_dates)
            all_signal_dates.update(sig_m7_dates)
            all_signal_dates.update(sig_m5_dates)
            all_signal_dates.update(sig_bw2_dates)
            all_signal_dates = sorted(all_signal_dates, reverse=True)[:20]

            if all_signal_dates:
                log_rows = []
                for ds in all_signal_dates:
                    gap_v = agg_vwks_sig[agg_vwks_sig['date_str'] == ds]['smooth_gap_pct'].values
                    gap_v = gap_v[0] if len(gap_v) > 0 else 0
                    m3_f = "✅ Q1" if ds in sig_m3_q1_dates else ("⚠️ Q2-4" if ds in sig_m3_dates else "—")
                    m7_f = "✅" if ds in sig_m7_dates else "—"
                    m5_f = "✅" if ds in sig_m5_dates else "—"
                    bw_f = "✅" if ds in sig_bw2_dates else "—"
                    log_rows.append({"Date": ds, "Gap %": f"{gap_v:.2f}", "M3": m3_f, "M7": m7_f, "M5": m5_f, "BW2%": bw_f})

                st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No signals detected in the selected window.")


# ==========================================
# TAB 8: INSTITUTIONAL SURFACE HEATMAP (LADDER)
# ==========================================
with tab_heatmap:
    st.header("🌡️ Options Surface Heatmap")
    st.markdown("A 3D grid visualizing exposure and flow across the entire matrix of strikes and expirations.")

    # --- CONTROLS ---
    c_heat_met, c_heat_side, c_heat_dte, c_heat_strike = st.columns([2, 1, 1, 1])
    with c_heat_met:
        # NEW: Added Notional Premium metric
        heat_metric = st.selectbox("Select Display Metric:",
                                   ["Gamma Exposure (Net GEX)", "Notional Delta (Net DEX)",
                                    "Notional Premium (Net Prem)", "Total Volume", "Daily Δ Open Interest",
                                    "Total Open Interest (+ Daily Δ)"],
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
                color_scale = [[0.0, '#5B2C6F'], [0.5, '#1e3a8a'], [1.0, '#00CC96']]
                zmid = 0
            else:
                color_scale = [[0.0, '#1e3a8a'], [1.0, '#00CC96']]
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
        else:
            st.warning("No data found for this specific DTE and Strike range combination.")
