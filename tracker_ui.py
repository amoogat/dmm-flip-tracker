"""
DMM Flip Tracker - Web UI (Compatible with older Streamlit)
Multi-user support via nicknames - no accounts needed!
"""

import streamlit as st
import requests
import json
import os
import time
from datetime import datetime
import statistics
import pandas as pd

# === COMPATIBILITY ===
def rerun():
    """Compatible rerun for both old and new Streamlit versions"""
    try:
        st.rerun()  # New Streamlit (1.27+)
    except AttributeError:
        st.experimental_rerun()  # Old Streamlit

def format_age(seconds):
    """Format seconds into human-readable time like notebook"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m" if secs == 0 else f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"

# === CONFIG ===
API_BASE = "https://prices.runescape.wiki/api/v1/dmm"
HEADERS = {"User-Agent": "DMM-Flip-Tracker/2026"}
HISTORY_FILE = "price_history.json"  # Shared - everyone benefits
USER_DATA_DIR = "user_data"  # Per-user data stored here

st.set_page_config(page_title="DMM Flip Tracker", page_icon="💰", layout="wide")

# === CUSTOM THEME CSS ===
st.markdown("""
<style>
    /* === IMPORTS === */
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');

    /* === ROOT VARIABLES === */
    :root {
        --gold: #D4AF37;
        --gold-light: #F4D03F;
        --gold-dark: #B8860B;
        --bg-dark: #0E1117;
        --bg-card: #1A1D24;
        --bg-card-hover: #252A34;
        --text-primary: #FAFAFA;
        --text-secondary: #A0A0A0;
        --green: #00D26A;
        --red: #FF4757;
        --orange: #FFA502;
    }

    /* === SCROLL FIX === */
    .main .block-container {
        max-height: none !important;
        overflow: visible !important;
    }
    section.main {
        overflow-y: auto !important;
    }
    [data-testid="stAppViewContainer"] {
        overflow-y: auto !important;
        background: linear-gradient(180deg, #0E1117 0%, #1A1D24 100%);
    }

    /* === SMOOTH TRANSITIONS === */
    * {
        transition: background-color 0.2s ease, border-color 0.2s ease, opacity 0.2s ease;
    }

    /* === TYPOGRAPHY === */
    h1, h2, h3 {
        font-family: 'Cinzel', serif !important;
        color: var(--gold) !important;
        text-shadow: 0 0 20px rgba(212, 175, 55, 0.3);
    }
    h1 {
        font-size: 2.5rem !important;
        letter-spacing: 2px;
        border-bottom: 2px solid var(--gold-dark);
        padding-bottom: 10px;
    }

    /* === SIDEBAR === */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #12151C 0%, #1A1D24 100%) !important;
        border-right: 1px solid var(--gold-dark);
    }
    [data-testid="stSidebar"] > div:first-child {
        background: transparent !important;
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.5rem;
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: var(--gold-light) !important;
        font-size: 1.1rem !important;
    }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span {
        color: var(--text-primary) !important;
    }
    [data-testid="stSidebarContent"] {
        background: transparent !important;
    }

    /* === TAB NAVIGATION === */
    .tab-container {
        display: flex;
        gap: 0;
        margin-bottom: 20px;
        border-bottom: 2px solid var(--gold-dark);
    }
    .tab-btn {
        flex: 1;
        padding: 12px 24px;
        background: transparent;
        border: none;
        border-bottom: 3px solid transparent;
        color: var(--text-secondary);
        font-family: 'Cinzel', serif;
        font-size: 1.1rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        margin-bottom: -2px;
    }
    .tab-btn:hover {
        color: var(--gold-light);
        background: rgba(212, 175, 55, 0.1);
    }
    .tab-btn.active {
        color: var(--gold);
        border-bottom: 3px solid var(--gold);
        background: rgba(212, 175, 55, 0.05);
    }

    /* === METRICS === */
    [data-testid="stMetric"] {
        background: var(--bg-card);
        border: 1px solid rgba(212, 175, 55, 0.3);
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
    }
    [data-testid="stMetric"]:hover {
        border-color: var(--gold);
        box-shadow: 0 4px 20px rgba(212, 175, 55, 0.2);
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-secondary) !important;
    }
    [data-testid="stMetricValue"] {
        color: var(--gold-light) !important;
        font-family: 'Cinzel', serif !important;
    }

    /* === DATAFRAMES === */
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(212, 175, 55, 0.2);
        border-radius: 10px;
        overflow: hidden;
    }
    [data-testid="stDataFrame"] table {
        font-family: 'Inter', sans-serif !important;
    }
    [data-testid="stDataFrame"] th {
        background: linear-gradient(180deg, #2A2F3A 0%, #1E222A 100%) !important;
        color: var(--gold) !important;
        font-weight: 600 !important;
        border-bottom: 2px solid var(--gold-dark) !important;
    }
    [data-testid="stDataFrame"] td {
        background: var(--bg-card) !important;
        border-bottom: 1px solid rgba(255,255,255,0.05) !important;
    }
    [data-testid="stDataFrame"] tr:hover td {
        background: var(--bg-card-hover) !important;
    }

    /* === BUTTONS === */
    .stButton > button {
        background: linear-gradient(180deg, var(--gold) 0%, var(--gold-dark) 100%);
        color: #1A1D24 !important;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        font-family: 'Inter', sans-serif;
        transition: all 0.3s ease;
        box-shadow: 0 2px 10px rgba(212, 175, 55, 0.3);
    }
    .stButton > button:hover {
        background: linear-gradient(180deg, var(--gold-light) 0%, var(--gold) 100%);
        box-shadow: 0 4px 20px rgba(212, 175, 55, 0.5);
        transform: translateY(-1px);
    }
    .stButton > button:active {
        transform: translateY(0px);
    }

    /* === INPUTS === */
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input,
    .stSelectbox > div > div > div {
        background: var(--bg-card) !important;
        border: 1px solid rgba(212, 175, 55, 0.3) !important;
        border-radius: 6px !important;
        color: var(--text-primary) !important;
    }
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus {
        border-color: var(--gold) !important;
        box-shadow: 0 0 10px rgba(212, 175, 55, 0.2) !important;
    }

    /* === CHECKBOXES === */
    .stCheckbox > label > span {
        color: var(--text-primary) !important;
    }

    /* === ALERTS/WARNINGS === */
    .stAlert {
        border-radius: 8px;
        border-left: 4px solid;
    }
    [data-baseweb="notification"] {
        background: var(--bg-card) !important;
    }

    /* === SUCCESS MESSAGES === */
    .element-container:has(.stSuccess) {
        animation: glow-green 2s ease-in-out;
    }
    @keyframes glow-green {
        0%, 100% { box-shadow: none; }
        50% { box-shadow: 0 0 20px rgba(0, 210, 106, 0.3); }
    }

    /* === ERROR MESSAGES === */
    .stError {
        background: rgba(255, 71, 87, 0.1) !important;
        border-color: var(--red) !important;
    }

    /* === WARNING MESSAGES === */
    .stWarning {
        background: rgba(255, 165, 2, 0.1) !important;
        border-color: var(--orange) !important;
    }

    /* === RADIO BUTTONS === */
    .stRadio > label {
        color: var(--text-primary) !important;
    }
    .stRadio > div {
        background: var(--bg-card);
        border-radius: 8px;
        padding: 10px;
        border: 1px solid rgba(212, 175, 55, 0.2);
    }

    /* === DIVIDERS === */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--gold-dark), transparent);
        margin: 20px 0;
    }

    /* === CAPTIONS === */
    .stCaption, small {
        color: var(--text-secondary) !important;
        font-style: italic;
    }

    /* === SUBHEADERS === */
    .stSubheader {
        color: var(--gold-light) !important;
        border-left: 3px solid var(--gold);
        padding-left: 10px;
    }

    /* === LOADING ANIMATION === */
    .stSpinner > div {
        border-top-color: var(--gold) !important;
    }

    /* === HIDE STREAMLIT BRANDING (keep header for sidebar toggle) === */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* === STICKY MENU BAR === */
    .menu-bar {
        position: sticky;
        top: 0;
        z-index: 999;
        background: linear-gradient(180deg, #1A1D24 0%, #12151C 100%);
        border-bottom: 2px solid var(--gold-dark);
        padding: 0;
        margin: -1rem -1rem 1rem -1rem;
        display: flex;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    }
    .menu-tab {
        flex: 1;
        padding: 15px 20px;
        text-align: center;
        font-family: 'Cinzel', serif;
        font-size: 1.1rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        border: none;
        background: transparent;
        color: var(--text-secondary);
        border-bottom: 3px solid transparent;
    }
    .menu-tab:hover {
        background: rgba(212, 175, 55, 0.1);
        color: var(--gold-light);
    }
    .menu-tab.active {
        color: var(--gold);
        background: rgba(212, 175, 55, 0.15);
        border-bottom: 3px solid var(--gold);
    }

    /* === CUSTOM SCROLLBAR === */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: var(--bg-dark);
    }
    ::-webkit-scrollbar-thumb {
        background: var(--gold-dark);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: var(--gold);
    }

    /* === FADE IN ANIMATION === */
    .main .block-container {
        animation: fadeIn 0.3s ease-in;
    }
    @keyframes fadeIn {
        from { opacity: 0.7; }
        to { opacity: 1; }
    }
</style>
""", unsafe_allow_html=True)

# === USER DATA FUNCTIONS ===
def get_user_dir(nickname):
    """Get or create user data directory"""
    if not nickname:
        return None
    safe_name = "".join(c for c in nickname if c.isalnum() or c in "-_").lower()
    user_dir = os.path.join(USER_DATA_DIR, safe_name)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir, exist_ok=True)
    return user_dir

def init_session_state():
    """Initialize session state for user data"""
    if 'positions' not in st.session_state:
        st.session_state['positions'] = []
    if 'alerts' not in st.session_state:
        st.session_state['alerts'] = []
    if 'plans' not in st.session_state:
        st.session_state['plans'] = {'items': [], 'start_time': None, 'start_capital': 0}
    if 'nickname' not in st.session_state:
        st.session_state['nickname'] = ''

def save_user_data(nickname):
    """Save user's positions, alerts, plans to their folder"""
    user_dir = get_user_dir(nickname)
    if not user_dir:
        return False
    try:
        with open(os.path.join(user_dir, 'positions.json'), 'w') as f:
            json.dump(st.session_state['positions'], f, indent=2)
        with open(os.path.join(user_dir, 'alerts.json'), 'w') as f:
            json.dump(st.session_state['alerts'], f, indent=2)
        with open(os.path.join(user_dir, 'plans.json'), 'w') as f:
            json.dump(st.session_state['plans'], f, indent=2)
        return True
    except:
        return False

def load_user_data(nickname):
    """Load user's positions, alerts, plans from their folder"""
    user_dir = get_user_dir(nickname)
    if not user_dir:
        return False
    try:
        pos_file = os.path.join(user_dir, 'positions.json')
        if os.path.exists(pos_file):
            with open(pos_file, 'r') as f:
                st.session_state['positions'] = json.load(f)

        alerts_file = os.path.join(user_dir, 'alerts.json')
        if os.path.exists(alerts_file):
            with open(alerts_file, 'r') as f:
                st.session_state['alerts'] = json.load(f)

        plans_file = os.path.join(user_dir, 'plans.json')
        if os.path.exists(plans_file):
            with open(plans_file, 'r') as f:
                st.session_state['plans'] = json.load(f)
        return True
    except:
        return False

# Initialize session state
init_session_state()

# === API DATA FUNCTIONS ===
@st.cache(ttl=60, allow_output_mutation=True)
def fetch_items():
    resp = requests.get(f"{API_BASE}/mapping", headers=HEADERS)
    items = {}
    names = {}
    for item in resp.json():
        items[item['id']] = {'name': item['name'], 'limit': item.get('limit', 1)}
        names[item['name'].lower()] = item['id']
    return items, names

@st.cache(ttl=120, allow_output_mutation=True)
def fetch_prices():
    resp = requests.get(f"{API_BASE}/latest", headers=HEADERS)
    return resp.json()['data']

@st.cache(ttl=120, allow_output_mutation=True)
def fetch_volumes():
    resp = requests.get(f"{API_BASE}/1h", headers=HEADERS)
    return resp.json()['data']

# === SHARED DATA FUNCTIONS (Price History - everyone benefits) ===
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

# === AUTO-SAVE HELPER ===
def auto_save():
    """Auto-save if user has a nickname set"""
    nickname = st.session_state.get('nickname', '')
    if nickname:
        save_user_data(nickname)

# === DATA FUNCTIONS (use session state + auto-save) ===
def load_positions():
    return st.session_state.get('positions', [])

def save_positions(positions):
    st.session_state['positions'] = positions
    auto_save()

def load_alerts():
    return st.session_state.get('alerts', [])

def save_alerts(alerts):
    st.session_state['alerts'] = alerts
    auto_save()

def load_plans():
    return st.session_state.get('plans', {'items': [], 'start_time': None, 'start_capital': 0})

def save_plans(plans):
    st.session_state['plans'] = plans
    auto_save()

def estimate_flips_per_hour(volume, buy_limit, age=0):
    """Estimate realistic flips per hour based on volume, buy limit, and freshness"""
    # Volume is total trades in 1 hour
    # We can only capture a fraction of that volume
    # Realistically: 5-10% of volume at best, capped by buy limit
    # Also cap by 4-hour buy limit (so per hour = limit/4)

    max_per_hour = buy_limit / 4
    volume_based = volume * 0.07  # assume we capture 7% of volume (realistic)

    base_estimate = min(max_per_hour, volume_based, volume)

    # Freshness penalty - stale prices mean less likely to execute
    if age > 300:  # > 5 min = very stale, likely won't execute
        freshness_mult = 0.1
    elif age > 180:  # 3-5 min = stale
        freshness_mult = 0.4
    elif age > 60:  # 1-3 min = getting stale
        freshness_mult = 0.7
    else:  # < 1 min = fresh
        freshness_mult = 1.0

    return base_estimate * freshness_mult

def get_freshness_info(prices_data, item_id):
    """Get freshness status and age for an item"""
    p = prices_data.get(str(item_id), {})
    high_time = p.get('highTime', 0)
    low_time = p.get('lowTime', 0)
    now = int(time.time())

    if not high_time or not low_time:
        return 9999, "❌ No data", 0.0

    age = max(now - high_time, now - low_time)

    if age > 300:
        return age, "🔴 Dead", 0.1
    elif age > 180:
        return age, "🟠 Stale", 0.4
    elif age > 60:
        return age, "🟡 OK", 0.7
    else:
        return age, "🟢 Fresh", 1.0

def style_dataframe(df, color_cols=None, format_cols=None):
    """Style a dataframe with colors and formatting"""
    if color_cols is None:
        color_cols = []
    if format_cols is None:
        format_cols = {}

    # Create styler
    styler = df.style

    # Apply number formatting
    format_dict = {}
    for col in df.columns:
        if col in ['Buy', 'Sell', 'Profit', 'Vol/hr', 'GP/hr', 'My Price', 'Market High', 'Market Low', 'Current High', 'Current Low', 'Diff', 'Target/hr', 'Done']:
            format_dict[col] = '{:,.0f}'
        elif col in ['Margin %']:
            format_dict[col] = '{:.2f}%'  # Add % symbol
        elif col in ['🔥Agg', '⚖️Bal', '🛡️Con', 'Stab', 'Limit', 'Qty', '#']:
            format_dict[col] = '{:.0f}'

    if format_dict:
        styler = styler.format(format_dict)

    # Always add Margin % to color columns if present
    if 'Margin %' in df.columns and 'Margin %' not in color_cols:
        color_cols = list(color_cols) + ['Margin %']

    # Apply color gradients (red to green)
    for col in color_cols:
        if col in df.columns:
            try:
                # Check if column has numeric data
                if df[col].dtype in ['int64', 'float64', 'int32', 'float32']:
                    styler = styler.background_gradient(subset=[col], cmap='RdYlGn')
            except:
                pass  # Skip if column can't be styled

    return styler

def check_alerts(alerts, prices, item_names):
    """Check which alerts are triggered and return list of triggered alerts"""
    triggered = []
    for alert in alerts:
        if not alert.get('enabled', True):
            continue

        item_id = alert.get('item_id')
        if not item_id:
            continue

        p = prices.get(str(item_id), {})
        curr_high = p.get('high', 0)
        curr_low = p.get('low', 0)

        # Check high price alerts
        if alert.get('high_above') and curr_high >= alert['high_above']:
            triggered.append({
                'item': alert['item'],
                'type': 'HIGH ≥',
                'target': alert['high_above'],
                'current': curr_high
            })
        if alert.get('high_below') and curr_high <= alert['high_below']:
            triggered.append({
                'item': alert['item'],
                'type': 'HIGH ≤',
                'target': alert['high_below'],
                'current': curr_high
            })

        # Check low price alerts
        if alert.get('low_above') and curr_low >= alert['low_above']:
            triggered.append({
                'item': alert['item'],
                'type': 'LOW ≥',
                'target': alert['low_above'],
                'current': curr_low
            })
        if alert.get('low_below') and curr_low <= alert['low_below']:
            triggered.append({
                'item': alert['item'],
                'type': 'LOW ≤',
                'target': alert['low_below'],
                'current': curr_low
            })

    return triggered

def record_prices(opps, history):
    now = int(time.time())
    for opp in opps:
        item_id = str(opp['id'])
        if item_id not in history:
            history[item_id] = []
        history[item_id].append({
            'timestamp': now, 'buy': opp['buy'], 'sell': opp['sell'],
            'margin_pct': opp['margin_pct'], 'volume': opp['volume']
        })
        if len(history[item_id]) > 120:
            history[item_id] = history[item_id][-120:]
    return history

def analyze_stability(item_id, history, items):
    h = history.get(str(item_id), [])
    if len(h) < 3:
        return None

    now = int(time.time())

    # BUG FIX: Only use recent data points (last 30 minutes)
    recent_h = [x for x in h if now - x.get('timestamp', 0) < 1800]
    if len(recent_h) < 3:
        # Fall back to last 10 points if not enough recent
        recent_h = h[-10:] if len(h) >= 3 else h

    margins = [x['margin_pct'] for x in recent_h]
    buy_prices = [x['buy'] for x in recent_h]
    sell_prices = [x['sell'] for x in recent_h]
    volumes_hist = [x.get('volume', 0) for x in recent_h]

    avg_margin = statistics.mean(margins)
    avg_buy = statistics.mean(buy_prices)
    avg_sell = statistics.mean(sell_prices)
    avg_volume = statistics.mean(volumes_hist) if volumes_hist else 0
    margin_std = statistics.stdev(margins) if len(margins) > 1 else 0

    # Check data freshness - when was last data point?
    last_timestamp = recent_h[-1].get('timestamp', 0) if recent_h else 0
    data_age = now - last_timestamp

    mid = len(buy_prices) // 2
    if mid > 0:
        first_half = statistics.mean(buy_prices[:mid])
        second_half = statistics.mean(buy_prices[mid:])
        price_change = ((second_half - first_half) / first_half * 100) if first_half else 0
        first_margin = statistics.mean(margins[:mid])
        second_margin = statistics.mean(margins[mid:])
        margin_change = second_margin - first_margin
    else:
        price_change = 0
        margin_change = 0

    if price_change > 10: price_trend = "🚀 Pumping"
    elif price_change < -10: price_trend = "📉 Dumping"
    elif price_change > 3: price_trend = "📈 Rising"
    elif price_change < -3: price_trend = "📉 Falling"
    else: price_trend = "→ Stable"

    if margin_change > 3: margin_trend = "💰 Expanding"
    elif margin_change < -3: margin_trend = "⚠️ Squeezing"
    else: margin_trend = "→ Stable"

    # BUG FIX: Penalize old data
    if data_age > 600:  # Data older than 10 min
        freshness_penalty = 30
    elif data_age > 300:  # 5-10 min
        freshness_penalty = 15
    else:
        freshness_penalty = 0

    score = max(0, 50 - margin_std * 10) + min(30, avg_margin) + (10 if "Stable" in price_trend else 0) + min(10, len(recent_h)) - freshness_penalty

    return {
        'avg_margin': avg_margin, 'avg_buy': int(avg_buy), 'avg_sell': int(avg_sell),
        'avg_volume': avg_volume, 'margin_std': margin_std, 'margin_trend': margin_trend,
        'price_trend': price_trend, 'price_change': price_change, 'stability_score': min(100, max(0, score)),
        'samples': len(recent_h), 'data_age': data_age,
        'latest_buy': recent_h[-1]['buy'], 'latest_sell': recent_h[-1]['sell'],
        'latest_margin': recent_h[-1]['margin_pct']
    }

def find_opportunities(items, prices, volumes, capital, min_margin=3, max_margin=30):
    import math
    opps = []
    now = int(time.time())

    for item_id_str, p in prices.items():
        item_id = int(item_id_str)
        if item_id not in items:
            continue

        item = items[item_id]
        high, low = p.get('high'), p.get('low')
        high_time, low_time = p.get('highTime'), p.get('lowTime')

        if not all([high, low, high_time, low_time]) or high <= low:
            continue

        age = max(now - high_time, now - low_time)
        if age > 300 or low < 10 or high / low > 2.0 or high > capital:
            continue

        vol = volumes.get(item_id_str, {})
        total_vol = (vol.get('highPriceVolume', 0) or 0) + (vol.get('lowPriceVolume', 0) or 0)
        if total_vol < 10:
            continue

        margin = high - low - int(high * 0.01)
        margin_pct = (margin / low) * 100
        if margin_pct < min_margin or margin_pct > max_margin:
            continue

        max_qty = min(capital // high, item['limit'])
        if max_qty < 1:
            continue

        # Calculate smart scores
        if age < 60:
            fresh_mult = 1.0
        elif age < 180:
            fresh_mult = 0.7
        else:
            fresh_mult = 0.4

        vol_score = math.log10(max(total_vol, 1)) * 25
        fresh_score = fresh_mult * 50
        profit_score = min(50, (margin * max_qty) / 100)

        aggressive = int(profit_score * 0.5 + vol_score * 0.3 + fresh_score * 0.2)
        balanced = int(profit_score * 0.33 + vol_score * 0.33 + fresh_score * 0.34)
        conservative = int(fresh_score * 0.4 + vol_score * 0.4 + profit_score * 0.2)

        opps.append({
            'id': item_id, 'name': item['name'], 'buy': high, 'sell': low,
            'margin': margin, 'margin_pct': margin_pct, 'volume': total_vol,
            'profit': margin * max_qty, 'qty': max_qty, 'age': age, 'limit': item['limit'],
            'smart_agg': aggressive, 'smart_bal': balanced, 'smart_con': conservative
        })

    opps.sort(key=lambda x: x['smart_agg'], reverse=True)  # Default sort by aggressive 🔥
    return opps

def get_stable_picks(items, history, prices, volumes, capital, filter_stale=True, filter_low_vol=True):
    stable = []
    now = int(time.time())
    import math

    for item_id_str in history.keys():
        item_id = int(item_id_str)
        if item_id not in items:
            continue

        a = analyze_stability(item_id, history, items)
        if not a or a['samples'] < 3 or a['stability_score'] < 20:
            continue

        # Get LIVE prices from API (not history!)
        p = prices.get(item_id_str, {})
        live_buy = p.get('high', 0)  # Instant buy price
        live_sell = p.get('low', 0)   # Instant sell price
        high_time = p.get('highTime', 0)
        low_time = p.get('lowTime', 0)
        age = max(now - high_time, now - low_time) if high_time and low_time else 9999

        # Skip if no live prices or can't afford
        if not live_buy or not live_sell or live_buy > capital:
            continue

        # Calculate max qty based on LIVE price
        max_qty = min(capital // live_buy, items[item_id]['limit'])
        if max_qty < 1:
            continue

        # Filter stale prices (> 10 min) - optional
        if filter_stale and age > 600:
            continue

        # Get current volume
        vol_data = volumes.get(item_id_str, {})
        vol = (vol_data.get('highPriceVolume', 0) or 0) + (vol_data.get('lowPriceVolume', 0) or 0)

        # Filter low volume items - optional
        if filter_low_vol and vol < 5:
            continue

        # Use LIVE prices for margin calculation
        margin = live_buy - live_sell - int(live_buy * 0.01)
        live_margin_pct = (margin / live_sell * 100) if live_sell > 0 else 0

        # Calculate smart scores for each strategy
        # Freshness multiplier
        if age < 60:
            fresh_mult = 1.0
        elif age < 180:
            fresh_mult = 0.7
        else:
            fresh_mult = 0.4

        vol_score = math.log10(max(vol, 1)) * 25
        fresh_score = fresh_mult * 50
        profit_score = min(50, margin * max_qty / 100)
        stability_score = a['stability_score']

        # Aggressive: profit > volume > fresh > stability
        aggressive = profit_score * 0.4 + vol_score * 0.3 + fresh_score * 0.2 + stability_score * 0.1
        # Balanced: equal weight
        balanced = profit_score * 0.25 + vol_score * 0.25 + fresh_score * 0.25 + stability_score * 0.25
        # Conservative: stability > fresh > volume > profit
        conservative = stability_score * 0.4 + fresh_score * 0.3 + vol_score * 0.2 + profit_score * 0.1

        stable.append({
            'name': items[item_id]['name'],
            'item_id': item_id,
            'buy': live_buy, 'sell': live_sell,  # LIVE prices!
            'avg_buy': a['avg_buy'], 'avg_sell': a['avg_sell'],
            'margin_pct': live_margin_pct, 'avg_margin': a['avg_margin'],  # LIVE margin!
            'margin_trend': a['margin_trend'], 'price_trend': a['price_trend'],
            'score': a['stability_score'], 'samples': a['samples'],
            'profit': margin * max_qty, 'qty': max_qty,
            'age': age, 'volume': vol,
            'smart_agg': int(aggressive),
            'smart_bal': int(balanced),
            'smart_con': int(conservative)
        })

    stable.sort(key=lambda x: x['smart_agg'], reverse=True)  # Default sort by aggressive 🔥
    return stable

# === LOAD DATA ===
try:
    items, item_names = fetch_items()
    prices = fetch_prices()
    volumes = fetch_volumes()
    history = load_history()
    data_ok = True
except Exception as e:
    st.error(f"Error: {e}")
    data_ok = False
    items, item_names, prices, volumes, history = {}, {}, {}, {}, {}

# === SIDEBAR ===
st.sidebar.title("💰 DMM Tracker")
st.sidebar.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

if st.sidebar.button("🔄 Refresh"):
    st.cache.clear()
    rerun()

# === USER NICKNAME (for saving/loading data) ===
st.sidebar.markdown("---")
st.sidebar.subheader("👤 Your Profile")
nickname_input = st.sidebar.text_input("Nickname", value=st.session_state.get('nickname', ''))

if st.sidebar.button("🚀 Start / Load"):
    if nickname_input:
        # Try to load existing data, or start fresh
        if load_user_data(nickname_input):
            st.session_state['nickname'] = nickname_input
            st.sidebar.success(f"Welcome back, {nickname_input}!")
        else:
            st.session_state['nickname'] = nickname_input
            st.sidebar.success(f"New profile: {nickname_input}")
        rerun()
    else:
        st.sidebar.warning("Enter a nickname first")

if st.session_state.get('nickname'):
    st.sidebar.success(f"👤 **{st.session_state['nickname']}** (auto-saving)")
else:
    st.sidebar.caption("Enter nickname to save your data")

st.sidebar.markdown("---")
capital = st.sidebar.number_input("💵 Your Capital (GP)", value=50000, min_value=1000, step=10000)
min_margin = st.sidebar.slider("Min Margin %", 1, 20, 3)
max_margin = st.sidebar.slider("Max Margin %", 10, 50, 30)

st.sidebar.markdown("---")
st.sidebar.subheader("🔧 Filters")
filter_stale = st.sidebar.checkbox("Filter stale prices (>10 min)", value=True)
filter_low_vol = st.sidebar.checkbox("Filter low volume (<5/hr)", value=True)
st.sidebar.caption("Uncheck to see all items (may include dead ones)")

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 Auto-Refresh")
# Use session_state to persist settings across reruns
if 'auto_refresh' not in st.session_state:
    st.session_state['auto_refresh'] = False  # Default OFF
if 'refresh_interval' not in st.session_state:
    st.session_state['refresh_interval'] = 60  # Default 60s

auto_refresh = st.sidebar.checkbox("Enable auto-refresh", value=st.session_state['auto_refresh'], key="auto_refresh_cb")
st.session_state['auto_refresh'] = auto_refresh

interval_options = [30, 60, 120, 300]
interval_idx = interval_options.index(st.session_state['refresh_interval']) if st.session_state['refresh_interval'] in interval_options else 1
refresh_interval = st.sidebar.selectbox("Refresh every", interval_options, index=interval_idx, format_func=lambda x: f"{x} seconds", key="refresh_int_sel")
st.session_state['refresh_interval'] = refresh_interval

st.sidebar.markdown("---")
st.sidebar.subheader("➕ Add GE Offer")
item_search = st.sidebar.text_input("Search item")
selected_item = None

if item_search and data_ok:
    matching = [n for n in item_names.keys() if item_search.lower() in n][:8]
    if matching:
        selected_item = st.sidebar.selectbox("Select", matching)

if selected_item:
    item_id = item_names[selected_item]
    p = prices.get(str(item_id), {})
    curr_high = p.get('high', 0)  # instant buy price
    curr_low = p.get('low', 0)    # instant sell price
    st.sidebar.caption(f"Instant buy: {curr_high:,} | Instant sell: {curr_low:,}")

    offer_type = st.sidebar.radio("Offer type", ["Buy Offer", "Sell Offer"])

    if offer_type == "Buy Offer":
        default_price = max(1, curr_low)  # usually offer below instant sell
        st.sidebar.caption("You're waiting to BUY. Alert if someone sells for MORE than your offer.")
    else:
        default_price = max(1, curr_high)  # usually offer above instant buy
        st.sidebar.caption("You're waiting to SELL. Alert if someone undercuts you.")

    my_price = st.sidebar.number_input("My offer price", value=default_price, min_value=1)
    qty = st.sidebar.number_input("Qty", value=1, min_value=1)

    if st.sidebar.button("Add Offer"):
        pos = load_positions()
        pos.append({
            'item': items[item_id]['name'],
            'item_id': item_id,
            'offer_type': 'buy' if offer_type == "Buy Offer" else 'sell',
            'my_price': int(my_price),
            'qty': int(qty)
        })
        save_positions(pos)
        rerun()

# === SIDEBAR: PRICE ALERTS ===
st.sidebar.markdown("---")
st.sidebar.subheader("🔔 Add Price Alert")
alert_search = st.sidebar.text_input("Search item for alert", key="alert_search")
alert_item = None

if alert_search and data_ok:
    alert_matching = [n for n in item_names.keys() if alert_search.lower() in n][:8]
    if alert_matching:
        alert_item = st.sidebar.selectbox("Select item", alert_matching, key="alert_select")

if alert_item:
    alert_item_id = item_names[alert_item]
    ap = prices.get(str(alert_item_id), {})
    alert_curr_high = ap.get('high', 0)
    alert_curr_low = ap.get('low', 0)
    st.sidebar.caption(f"Current: High={alert_curr_high:,} | Low={alert_curr_low:,}")

    alert_type = st.sidebar.selectbox("Alert when...", [
        "High goes ABOVE",
        "High goes BELOW",
        "Low goes ABOVE",
        "Low goes BELOW"
    ])

    if "High" in alert_type:
        default_val = max(1, alert_curr_high)
    else:
        default_val = max(1, alert_curr_low)

    alert_price = st.sidebar.number_input("Target price", value=default_val, min_value=1, key="alert_price")

    # Check if condition is already met
    already_met = False
    already_msg = ""
    if alert_type == "High goes ABOVE" and alert_curr_high >= alert_price:
        already_met = True
        already_msg = f"High is already {alert_curr_high:,} (≥ {alert_price:,})"
    elif alert_type == "High goes BELOW" and alert_curr_high <= alert_price:
        already_met = True
        already_msg = f"High is already {alert_curr_high:,} (≤ {alert_price:,})"
    elif alert_type == "Low goes ABOVE" and alert_curr_low >= alert_price:
        already_met = True
        already_msg = f"Low is already {alert_curr_low:,} (≥ {alert_price:,})"
    elif alert_type == "Low goes BELOW" and alert_curr_low <= alert_price:
        already_met = True
        already_msg = f"Low is already {alert_curr_low:,} (≤ {alert_price:,})"

    if already_met:
        st.sidebar.warning(f"⚠️ Already there! {already_msg}")
    else:
        if st.sidebar.button("Add Alert"):
            alerts_list = load_alerts()
            new_alert = {
                'item': items[alert_item_id]['name'],
                'item_id': alert_item_id,
                'enabled': True
            }
            if alert_type == "High goes ABOVE":
                new_alert['high_above'] = int(alert_price)
            elif alert_type == "High goes BELOW":
                new_alert['high_below'] = int(alert_price)
            elif alert_type == "Low goes ABOVE":
                new_alert['low_above'] = int(alert_price)
            elif alert_type == "Low goes BELOW":
                new_alert['low_below'] = int(alert_price)

            alerts_list.append(new_alert)
            save_alerts(alerts_list)
            rerun()

# === MAIN ===
st.markdown("""
<h1 style="text-align: center; margin-bottom: 5px;">
    ⚔️ DMM 2026 Flip Tracker ⚔️
</h1>
<p style="text-align: center; color: #A0A0A0; margin-top: 0;">
    Real-time margins • Smart scoring • Multi-user
</p>
""", unsafe_allow_html=True)

if not data_ok:
    st.stop()

# Get data
opps = find_opportunities(items, prices, volumes, capital, min_margin, max_margin)
if opps:
    history = record_prices(opps, history)
    save_history(history)

stable = get_stable_picks(items, history, prices, volumes, capital, filter_stale, filter_low_vol)
positions = load_positions()
price_alerts = load_alerts()

# === MENU BAR ===
if 'view' not in st.session_state:
    st.session_state['view'] = 'dashboard'

current_view = st.session_state.get('view', 'dashboard')
dash_active = "active" if current_view == 'dashboard' else ""
plan_active = "active" if current_view == 'planner' else ""

# Render menu bar HTML
st.markdown(f"""
<div class="menu-bar">
    <div class="menu-tab {dash_active}" id="dash-tab">📊 Dashboard</div>
    <div class="menu-tab {plan_active}" id="plan-tab">📋 Smart Planner</div>
</div>
""", unsafe_allow_html=True)

# Hidden buttons for actual navigation (styled to be minimal)
st.markdown("""
<style>
    div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) {
        margin-top: -15px;
        margin-bottom: 10px;
    }
    div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) button {
        background: transparent !important;
        border: none !important;
        color: transparent !important;
        height: 35px;
        box-shadow: none !important;
    }
    div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) button:hover {
        background: rgba(212, 175, 55, 0.1) !important;
    }
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    if st.button("​", key="tab_dash"):  # Zero-width space
        st.session_state['view'] = 'dashboard'
        rerun()
with col2:
    if st.button("​", key="tab_plan"):  # Zero-width space
        st.session_state['view'] = 'planner'
        rerun()

view = st.session_state.get('view', 'dashboard')

# === CHECK PRICE ALERTS (always check, regardless of view) ===
triggered_alerts = check_alerts(price_alerts, prices, item_names)

# Sound + Toast for triggered alerts
if triggered_alerts:
    st.markdown("""
        <audio autoplay>
            <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
        </audio>
    """, unsafe_allow_html=True)
    st.error("### 🔔 PRICE ALERTS TRIGGERED!")
    for ta in triggered_alerts:
        st.warning(f"🔔 **{ta['item']}**: {ta['type']} {ta['target']:,} (Current: {ta['current']:,})")

# ============================================
# SMART PLANNER VIEW
# ============================================
if view == 'planner':
    st.subheader("📋 Smart Flip Planner")
    st.caption("Auto-generates an optimal flip plan based on your capital, using stable picks and top opportunities.")

    # Planner capital input
    planner_capital = st.number_input("💵 Enter your starting capital (GP)", value=capital, min_value=1000, step=10000, key="planner_cap")

    # Strategy selector
    strategy = st.selectbox("Strategy", ["Balanced (Mix of stable + high profit)", "Conservative (Stable picks only)", "Aggressive (Highest profit potential)"])

    if st.button("🧠 Generate Smart Plan"):
        # Combine stable picks and opportunities, score them
        all_items = []

        # Add stable picks with bonus for stability
        for s in stable:
            if s['buy'] <= planner_capital:
                vol_data = volumes.get(str(item_names.get(s['name'].lower(), 0)), {})
                vol = (vol_data.get('highPriceVolume', 0) or 0) + (vol_data.get('lowPriceVolume', 0) or 0)
                item_id = item_names.get(s['name'].lower())
                limit = items.get(item_id, {}).get('limit', 1) if item_id else 1

                # Get freshness
                age, fresh_status, fresh_mult = get_freshness_info(prices, item_id)

                # Skip items that are too stale (no point planning dead items)
                if fresh_mult < 0.3:
                    continue

                est_flips = estimate_flips_per_hour(vol, limit, age)
                margin = s['buy'] - s.get('sell', 0) - int(s['buy'] * 0.01)

                all_items.append({
                    'name': s['name'],
                    'item_id': item_id,
                    'buy': s['buy'],
                    'margin': margin,
                    'margin_pct': s['margin_pct'],
                    'volume': vol,
                    'limit': limit,
                    'age': age,
                    'freshness': fresh_status,
                    'fresh_mult': fresh_mult,
                    'est_flips_hr': est_flips,
                    'est_profit_hr': est_flips * margin,
                    'score': s['score'],
                    'source': 'Stable',
                    'stability_bonus': 20
                })

        # Add opportunities (already have freshness via age field)
        for o in opps:
            if o['buy'] <= planner_capital:
                age = o.get('age', 0)
                _, fresh_status, fresh_mult = get_freshness_info(prices, o['id'])

                # Skip stale items
                if fresh_mult < 0.3:
                    continue

                est_flips = estimate_flips_per_hour(o['volume'], o['limit'], age)

                all_items.append({
                    'name': o['name'],
                    'item_id': o['id'],
                    'buy': o['buy'],
                    'margin': o['margin'],
                    'margin_pct': o['margin_pct'],
                    'volume': o['volume'],
                    'limit': o['limit'],
                    'age': age,
                    'freshness': fresh_status,
                    'fresh_mult': fresh_mult,
                    'est_flips_hr': est_flips,
                    'est_profit_hr': est_flips * margin,
                    'score': 50,  # base score for opps
                    'source': 'Opportunity',
                    'stability_bonus': 0
                })

        # Remove duplicates (prefer stable version)
        seen = set()
        unique_items = []
        for item in all_items:
            if item['name'] not in seen:
                seen.add(item['name'])
                unique_items.append(item)

        # Score based on strategy - VOLUME and FRESHNESS are king!
        for item in unique_items:
            vol = item.get('volume', 0)
            fresh_mult = item.get('fresh_mult', 1.0)

            # Volume score: log scale so high volume items stand out
            # 100 vol = 2, 1000 vol = 3, 10000 vol = 4
            import math
            vol_score = math.log10(max(vol, 1)) * 50

            # Freshness bonus (fresh = 1.0, stale = 0.4, dead = 0.1)
            freshness_score = fresh_mult * 100

            # Base scores
            profit_score = item['est_profit_hr']
            stability_score = item.get('score', 50) + item.get('stability_bonus', 0)

            if strategy.startswith("Balanced"):
                # Volume 30%, Freshness 30%, Profit 25%, Stability 15%
                item['plan_score'] = vol_score * 0.3 + freshness_score * 0.3 + profit_score * 0.25 + stability_score * 0.15
            elif strategy.startswith("Conservative"):
                # Stability 35%, Freshness 30%, Volume 25%, Profit 10%
                item['plan_score'] = stability_score * 0.35 + freshness_score * 0.3 + vol_score * 0.25 + profit_score * 0.1
            else:  # Aggressive
                # Profit 35%, Volume 30%, Freshness 25%, Stability 10%
                item['plan_score'] = profit_score * 0.35 + vol_score * 0.3 + freshness_score * 0.25 + stability_score * 0.1

        # Sort by plan score
        unique_items.sort(key=lambda x: x['plan_score'], reverse=True)

        # Allocate capital to top items
        remaining_capital = planner_capital
        plan_items = []
        total_est_profit = 0

        for item in unique_items:
            if remaining_capital < item['buy']:
                continue

            # How many can we buy?
            max_qty = min(remaining_capital // item['buy'], item['limit'])
            if max_qty < 1:
                continue

            # Allocate (use up to 30% of remaining capital per item for diversification)
            max_alloc = remaining_capital * 0.3
            qty = min(max_qty, int(max_alloc // item['buy']))
            if qty < 1:
                qty = 1

            cost = qty * item['buy']
            remaining_capital -= cost

            item['allocated_qty'] = qty
            item['allocated_cost'] = cost
            item['projected_profit_hr'] = item['est_flips_hr'] * item['margin'] * (qty / item['limit']) if item['limit'] > 0 else 0
            plan_items.append(item)
            total_est_profit += item['projected_profit_hr']

            if len(plan_items) >= 8 or remaining_capital < 100:
                break

        # Save the generated plan with volume and freshness
        new_plan = {
            'items': [{
                'item': p['name'],
                'item_id': p['item_id'],
                'target_per_hour': max(1, int(p['est_flips_hr'])),
                'est_per_hour': p['est_flips_hr'],
                'margin': p['margin'],
                'volume': p.get('volume', 0),
                'freshness': p.get('freshness', '?'),
                'qty': p['allocated_qty'],
                'cost': p['allocated_cost'],
                'completed': 0,
                'added_time': int(time.time())
            } for p in plan_items],
            'start_time': int(time.time()),
            'start_capital': planner_capital,
            'strategy': strategy
        }
        save_plans(new_plan)

        # Show what was picked with volume/freshness info
        st.success(f"✅ Plan generated! {len(plan_items)} items, using {planner_capital - remaining_capital:,} GP")
        st.caption("Items picked based on: Volume + Freshness + Profit + Stability")
        rerun()

    # Show current plan
    plans = load_plans()
    # --- Add Custom Item Section ---
    st.markdown("---")
    st.subheader("➕ Add Custom Item")
    custom_cols = st.columns([3, 1, 1, 1, 1])
    custom_search = custom_cols[0].text_input("Search item", key="custom_plan_search")

    custom_item = None
    if custom_search and data_ok:
        custom_matching = [n for n in item_names.keys() if custom_search.lower() in n][:5]
        if custom_matching:
            custom_item = custom_cols[0].selectbox("", custom_matching, key="custom_plan_select")

    custom_target = custom_cols[1].number_input("Target/hr", value=10, min_value=1, key="custom_target")
    custom_margin = custom_cols[2].number_input("Margin", value=100, min_value=1, key="custom_margin")
    custom_qty = custom_cols[3].number_input("Qty", value=1, min_value=1, key="custom_qty")

    if custom_cols[4].button("Add", key="add_custom"):
        if custom_item:
            custom_item_id = item_names.get(custom_item)
            pp = prices.get(str(custom_item_id), {}) if custom_item_id else {}
            actual_margin = pp.get('high', 0) - pp.get('low', 0) - int(pp.get('high', 0) * 0.01)

            plans = load_plans()
            if not plans['start_time']:
                plans['start_time'] = int(time.time())
                plans['start_capital'] = planner_capital
            plans['items'].append({
                'item': items[custom_item_id]['name'] if custom_item_id else custom_search,
                'item_id': custom_item_id,
                'target_per_hour': custom_target,
                'margin': actual_margin if actual_margin > 0 else custom_margin,
                'qty': custom_qty,
                'cost': (pp.get('high', 0) or custom_margin) * custom_qty,
                'completed': 0,
                'added_time': int(time.time())
            })
            save_plans(plans)
            rerun()

    # --- Current Plan Display ---
    plans = load_plans()
    if plans['items']:
        st.markdown("---")
        st.subheader("📊 Current Plan")

        session_start = plans.get('start_time', int(time.time()))
        hours_elapsed = max(0.01, (int(time.time()) - session_start) / 3600)
        start_cap = plans.get('start_capital', planner_capital)
        strat = plans.get('strategy', 'Custom' if not plans.get('strategy') else plans.get('strategy'))

        st.caption(f"Strategy: {strat} | Session: {hours_elapsed:.1f} hrs | Capital: {start_cap:,} GP")

        plan_data = []
        total_profit_hr = 0
        total_completed = 0
        stale_warnings = []

        for i, item in enumerate(plans['items']):
            target = item.get('target_per_hour', 0)
            completed = item.get('completed', 0)
            margin = item.get('margin', 0)
            qty = item.get('qty', 1)
            expected = target * hours_elapsed

            # Get LIVE freshness and volume
            item_id = item.get('item_id')
            age, fresh_status, fresh_mult = get_freshness_info(prices, item_id)
            vol_data = volumes.get(str(item_id), {}) if item_id else {}
            live_vol = (vol_data.get('highPriceVolume', 0) or 0) + (vol_data.get('lowPriceVolume', 0) or 0)

            # Warn if item went stale
            if fresh_mult < 0.5:
                stale_warnings.append(f"⚠️ {item['item']} is {fresh_status} - may not execute!")

            progress = (completed / expected * 100) if expected > 0 else 0

            # Adjust profit estimate by freshness (stale = less likely to work)
            realistic_profit_hr = target * margin * fresh_mult

            if progress >= 100:
                status = "🟢 On track"
            elif progress >= 60:
                status = "🟡 Behind"
            else:
                status = "🔴 Far behind"

            plan_data.append({
                '#': i + 1,
                'Item': item['item'],
                'Vol/hr': live_vol,
                'Fresh': fresh_status,
                'Target/hr': target,
                'Done': completed,
                'Progress': f"{progress:.0f}%",
                'Status': status,
                'GP/hr': int(realistic_profit_hr)
            })
            total_profit_hr += realistic_profit_hr
            total_completed += completed

        # Show stale warnings at top
        if stale_warnings:
            st.warning("Some items have stale prices - they may not execute!")
            for warn in stale_warnings[:3]:
                st.caption(warn)

        df = pd.DataFrame(plan_data)
        styled_df = style_dataframe(df, color_cols=['Vol/hr', 'GP/hr'])
        st.dataframe(styled_df)

        st.markdown(f"### 💰 Realistic Est: {total_profit_hr:,.0f} GP/hr | Completed: {total_completed} flips")
        st.caption("GP/hr adjusted for freshness - stale items count less")

        # Editable items with auto-save
        st.write("**Edit Items:**")
        for i, item in enumerate(plans['items']):
            cols = st.columns([3, 2, 2, 1])
            cols[0].write(f"**{item['item']}**")

            # Use session state keys to track changes properly
            done_key = f"done_{i}"
            target_key = f"target_{i}"

            new_completed = cols[1].number_input(
                "Done",
                value=item.get('completed', 0),
                min_value=0,
                key=done_key
            )
            new_target = cols[2].number_input(
                "Tgt/hr",
                value=item.get('target_per_hour', 1),
                min_value=1,
                key=target_key
            )

            if cols[3].button("❌", key=f"del_{i}"):
                plans['items'].pop(i)
                save_plans(plans)
                rerun()

            # Auto-save changes immediately
            if new_completed != item.get('completed', 0):
                plans['items'][i]['completed'] = new_completed
                save_plans(plans)
            if new_target != item.get('target_per_hour', 1):
                plans['items'][i]['target_per_hour'] = new_target
                save_plans(plans)

        # Reset button
        if st.button("🔄 Reset Plan"):
            save_plans({'items': [], 'start_time': None, 'start_capital': 0})
            rerun()

    else:
        st.info("👆 Generate a smart plan above, or add custom items manually!")

# ============================================
# DASHBOARD VIEW
# ============================================
else:
        # === METRICS ROW ===
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💵 Capital", f"{capital:,}")
    c2.metric("🔥 Opportunities", len(opps))
    c3.metric("⭐ Stable Picks", len(stable))
    c4.metric("📊 GE Offers", len(positions))
    c5.metric("🔔 Alerts", f"{len([a for a in price_alerts if a.get('enabled', True)])}/{len(price_alerts)}")

    st.markdown("---")

    # === SECTION: YOUR GE OFFERS (only show if any) ===
    alerts = []
    if positions:
        st.subheader("📊 Your GE Offers")
        pos_data = []
        for i, pos in enumerate(positions):
            item_id = pos.get('item_id') or item_names.get(pos['item'].lower())
            if not item_id:
                continue

            p = prices.get(str(item_id), {})
            curr_high = p.get('high', 0)  # what buyers are paying (instant buy)
            curr_low = p.get('low', 0)    # what sellers are asking (instant sell)

            # Handle old format positions (convert to new format display)
            if 'offer_type' not in pos:
                # Legacy position - show as-is
                offer_type = 'legacy'
                my_price = pos.get('bought_at', 0)
                status = "⚠️ Old format"
                diff = 0
            else:
                offer_type = pos['offer_type']
                my_price = pos['my_price']

                if offer_type == 'sell':
                    # SELL offer: alert if someone undercuts (curr_high < my_price)
                    diff = curr_high - my_price
                    if curr_high < my_price:
                        status = f"🚨 UNDERCUT by {abs(diff):,}!"
                        alerts.append(f"🚨 {pos['item']}: UNDERCUT! Market @ {curr_high:,}, you @ {my_price:,}")
                    elif curr_high == my_price:
                        status = "✅ Best price"
                    else:
                        status = f"✅ OK (+{diff:,} buffer)"
                else:
                    # BUY offer: alert if someone paying more (curr_low > my_price)
                    diff = curr_low - my_price
                    if curr_low > my_price:
                        status = f"🚨 OUTBID by {diff:,}!"
                        alerts.append(f"🚨 {pos['item']}: OUTBID! Market @ {curr_low:,}, you @ {my_price:,}")
                    elif curr_low == my_price:
                        status = "✅ Best price"
                    else:
                        status = f"✅ OK ({diff:,} below)"

            pos_data.append({
                '#': i + 1,
                'Item': pos['item'],
                'Type': '🔵 BUY' if offer_type == 'buy' else ('🟢 SELL' if offer_type == 'sell' else '⚪ ?'),
                'My Price': my_price,
                'Market High': curr_high,
                'Market Low': curr_low,
                'Qty': pos.get('qty', 0),
                'Status': status,
                'Diff': diff
            })

        # Show alerts at top if any
        if alerts:
            st.error("### ⚠️ ALERTS")
            for alert in alerts:
                st.warning(alert)

        if pos_data:
            df = pd.DataFrame(pos_data)
            styled_df = style_dataframe(df, color_cols=['Diff'])
            st.dataframe(styled_df)

        # Delete buttons in a row
        st.write("Remove offer:")
        cols = st.columns(min(len(positions), 8))
        for i, pos in enumerate(positions[:8]):
            if cols[i].button(f"❌ {i+1}", key=f"rm{i}"):
                positions.pop(i)
                save_positions(positions)
                rerun()

        st.caption("🔵 BUY = waiting to buy | 🟢 SELL = waiting to sell")
        st.markdown("---")

    # === SECTION: PRICE ALERTS (only show if any) ===
    if price_alerts:
        st.subheader("🔔 Price Alerts")
        alert_data = []
        for i, alert in enumerate(price_alerts):
            item_id = alert.get('item_id')
            p = prices.get(str(item_id), {}) if item_id else {}
            curr_high = p.get('high', 0)
            curr_low = p.get('low', 0)

            # Determine alert condition
            conditions = []
            if alert.get('high_above'):
                conditions.append(f"High ≥ {alert['high_above']:,}")
            if alert.get('high_below'):
                conditions.append(f"High ≤ {alert['high_below']:,}")
            if alert.get('low_above'):
                conditions.append(f"Low ≥ {alert['low_above']:,}")
            if alert.get('low_below'):
                conditions.append(f"Low ≤ {alert['low_below']:,}")

            enabled = alert.get('enabled', True)

            alert_data.append({
                '#': i + 1,
                'Item': alert['item'],
                'Condition': ', '.join(conditions),
                'Current High': curr_high,
                'Current Low': curr_low,
                'Enabled': '✅ ON' if enabled else '❌ OFF'
            })

        df = pd.DataFrame(alert_data)
        st.dataframe(df)

        # Toggle and delete buttons
        st.write("Toggle/Delete alerts:")
        cols = st.columns(min(len(price_alerts) * 2, 16))
        col_idx = 0
        for i, alert in enumerate(price_alerts[:8]):
            enabled = alert.get('enabled', True)
            # Toggle button
            if cols[col_idx].button(f"{'🔇' if enabled else '🔔'}{i+1}", key=f"tog{i}"):
                price_alerts[i]['enabled'] = not enabled
                save_alerts(price_alerts)
                rerun()
            col_idx += 1
            # Delete button
            if cols[col_idx].button(f"❌{i+1}", key=f"del{i}"):
                price_alerts.pop(i)
                save_alerts(price_alerts)
                rerun()
            col_idx += 1

        st.caption("🔔 = Enable | 🔇 = Disable | ❌ = Delete")
        st.markdown("---")

    # === SECTION: STABLE PICKS ===
    st.subheader("⭐ Stable Picks (Proven Margins)")
    if stable:
        st.caption(f"Items with consistent margins over time. Tracking {len(history)} items. Click column headers to sort!")

        stable_data = []
        for s in stable:
            # Freshness indicator
            age = s.get('age', 9999)
            if age < 60:
                freshness = "🟢"
            elif age < 180:
                freshness = "🟡"
            elif age < 600:
                freshness = "🟠"
            else:
                freshness = "🔴"

            stable_data.append({
                'Item': s['name'],
                'Buy': s['buy'],
                'Sell': s['sell'],
                'Margin %': round(s['margin_pct'], 1),
                'Vol/hr': s.get('volume', 0),
                'Age': format_age(age),
                'Fresh': freshness,
                'Stab': s.get('score', 0),
                'Price': s.get('price_trend', '—'),
                'Margin': s.get('margin_trend', '—'),
                '🔥Agg': s.get('smart_agg', 0),
                '⚖️Bal': s.get('smart_bal', 0),
                '🛡️Con': s.get('smart_con', 0),
                'Profit': s['profit'],
                'Limit': items.get(s.get('item_id'), {}).get('limit', 0)
            })
        df = pd.DataFrame(stable_data)
        styled_df = style_dataframe(df, color_cols=['Profit', 'Vol/hr', 'Stab', '🔥Agg', '⚖️Bal', '🛡️Con'])
        st.dataframe(styled_df)
        st.caption("Stab=Stability Score | Price/Margin=Trends | 🔥Agg | ⚖️Bal | 🛡️Con - Click headers to sort!")
    else:
        st.info(f"Building data... tracking {len(history)} items. Keep page open!")

    st.markdown("---")

    # === SECTION: TOP OPPORTUNITIES ===
    st.subheader("🔥 Top Opportunities")
    if opps:
        st.caption("Sorted by 🔥Aggressive. Click column headers to re-sort!")

        opp_data = []
        for opp in opps:
            # Freshness indicator
            age = opp['age']
            if age < 60:
                freshness = "🟢"
            elif age < 180:
                freshness = "🟡"
            elif age < 600:
                freshness = "🟠"
            else:
                freshness = "🔴"

            # Get stability/trend data if available
            analysis = analyze_stability(opp['id'], history, items)
            stab = int(analysis['stability_score']) if analysis else 0
            trend = analysis['price_trend'] if analysis else '—'

            opp_data.append({
                'Item': opp['name'],
                'Buy': opp['buy'],
                'Sell': opp['sell'],
                'Margin %': round(opp['margin_pct'], 1),
                'Vol/hr': opp['volume'],
                'Age': format_age(age),
                'Fresh': freshness,
                'Stab': stab,
                'Trend': trend,
                '🔥Agg': opp['smart_agg'],
                '⚖️Bal': opp['smart_bal'],
                '🛡️Con': opp['smart_con'],
                'Profit': opp['profit'],
                'Limit': opp['limit']
            })
        df = pd.DataFrame(opp_data)
        styled_df = style_dataframe(df, color_cols=['Profit', 'Vol/hr', 'Stab', '🔥Agg', '⚖️Bal', '🛡️Con'])
        st.dataframe(styled_df)
        st.caption("Stab=Stability | Trend=Price direction | 🔥Agg | ⚖️Bal | 🛡️Con - Click headers to sort!")
    else:
        st.info("No opportunities with current filters")

    st.markdown("---")
    st.caption(f"Data: {len(history)} items tracked | {sum(len(h) for h in history.values())} samples | Synced with notebook")

# === AUTO-REFRESH ===
if auto_refresh:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)
    st.caption(f"🔄 Auto-refreshing every {refresh_interval}s")
