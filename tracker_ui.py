"""
DMM Flip Tracker - Web UI (Compatible with older Streamlit)
Multi-user support via nicknames - no accounts needed!
"""

import streamlit as st
import requests
import json
import os
import time
from datetime import datetime, timezone, timedelta

# Pacific timezone (PST/PDT - handles daylight saving automatically isn't available in stdlib,
# so we'll use fixed offset; user is in Pacific)
try:
    from zoneinfo import ZoneInfo
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
except ImportError:
    # Fallback for older Python - use fixed offset (PST = UTC-8)
    PACIFIC_TZ = timezone(timedelta(hours=-8))
import statistics
import pandas as pd
import numpy as np

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

# === BREACH SYSTEM ===
BREACH_HOURS_UTC = [2, 10, 19]  # Breach times in UTC
BREACH_DURATION_HOURS = 2  # Post-breach window duration

# Items known to have post-breach margin boosts (from analysis)
BREACH_ITEMS = {
    3024: {'name': 'Super restore(4)', 'boost': 25.8},
    391: {'name': 'Manta ray', 'boost': 14.2},
    6685: {'name': 'Saradomin brew(4)', 'boost': 12.6},
    385: {'name': 'Shark', 'boost': 9.7},
    9075: {'name': 'Astral rune', 'boost': 6.3},
    560: {'name': 'Death rune', 'boost': 5.1},
}

def get_breach_info():
    """Get current breach status and countdown to next breach"""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    current_minute = now.minute

    # Check if we're in a post-breach window (0-2 hours after breach)
    in_post_breach = False
    current_breach = None
    for breach_hour in BREACH_HOURS_UTC:
        if breach_hour <= current_hour < breach_hour + BREACH_DURATION_HOURS:
            in_post_breach = True
            current_breach = breach_hour
            break

    # Find next breach
    next_breach = None
    for breach_hour in sorted(BREACH_HOURS_UTC):
        if breach_hour > current_hour or (breach_hour == current_hour and current_minute == 0):
            next_breach = breach_hour
            break

    # If no breach found today, next breach is tomorrow's first
    if next_breach is None:
        next_breach = BREACH_HOURS_UTC[0]
        hours_until = (24 - current_hour) + next_breach
    else:
        hours_until = next_breach - current_hour

    mins_until = (60 - current_minute) % 60
    if mins_until > 0:
        hours_until -= 1

    # Format countdown
    if hours_until < 0:
        hours_until += 24

    countdown = f"{hours_until}h {mins_until}m"

    # Calculate Pacific time for next breach
    next_breach_utc = now.replace(hour=next_breach, minute=0, second=0, microsecond=0)
    if next_breach <= current_hour and not (next_breach == current_hour and current_minute == 0):
        next_breach_utc = next_breach_utc + timedelta(days=1)
    next_breach_pacific = next_breach_utc.astimezone(PACIFIC_TZ)
    next_breach_pacific_str = next_breach_pacific.strftime("%I:%M %p").lstrip('0')

    # Current breach Pacific time (if in post-breach)
    current_breach_pacific_str = None
    if current_breach is not None:
        current_breach_utc = now.replace(hour=current_breach, minute=0, second=0, microsecond=0)
        current_breach_pacific = current_breach_utc.astimezone(PACIFIC_TZ)
        current_breach_pacific_str = current_breach_pacific.strftime("%I:%M %p").lstrip('0')

    return {
        'in_post_breach': in_post_breach,
        'current_breach': current_breach,
        'current_breach_pacific': current_breach_pacific_str,
        'next_breach': next_breach,
        'next_breach_pacific': next_breach_pacific_str,
        'countdown': countdown,
        'hours_until': hours_until + (mins_until / 60)
    }

def scan_breach_items(prices, volumes, items, item_names):
    """Scan for items with good margins during post-breach window"""
    breach_opps = []

    for item_id, info in BREACH_ITEMS.items():
        item_id_str = str(item_id)
        if item_id_str not in prices:
            continue

        p = prices[item_id_str]
        v = volumes.get(item_id_str, {})

        high = p.get('high', 0)
        low = p.get('low', 0)

        if not high or not low or high <= low:
            continue

        margin = high - low - int(high * 0.01)
        margin_pct = (margin / low) * 100 if low > 0 else 0

        vol = (v.get('highPriceVolume', 0) or 0) + (v.get('lowPriceVolume', 0) or 0)

        # Get item limit
        limit = items.get(item_id, {}).get('limit', 1)

        breach_opps.append({
            'name': info['name'],
            'item_id': item_id,
            'buy': high,
            'sell': low,
            'margin': margin,
            'margin_pct': margin_pct,
            'volume': vol,
            'limit': limit,
            'boost': info['boost']
        })

    # Sort by boost (known margin increase)
    breach_opps.sort(key=lambda x: -x['boost'])
    return breach_opps

def fetch_breach_scanner_data():
    """Fetch timeseries data to find current best breach items dynamically"""
    try:
        # Get high-volume consumables to scan
        scan_items = [
            3024, 6685, 385, 391, 11936,  # Food/pots
            560, 562, 555, 557, 9075,  # Runes
            2440, 2436, 2442, 3040,  # Combat pots
            892, 890, 888,  # Arrows
        ]

        results = []
        now = datetime.now(timezone.utc)

        for item_id in scan_items:
            try:
                resp = requests.get(
                    f"https://prices.runescape.wiki/api/v1/dmm/timeseries?id={item_id}&timestep=1h",
                    headers={"User-Agent": "DMM-Flip-Tracker/2026"},
                    timeout=5
                )
                data = resp.json().get('data', [])[-48:]

                if len(data) < 10:
                    continue

                # Analyze post-breach vs other (margins AND prices)
                post_margins = []
                other_margins = []
                post_prices = []
                other_prices = []

                for point in data:
                    ts = point['timestamp']
                    high = point.get('avgHighPrice') or 0
                    low = point.get('avgLowPrice') or 0

                    if high > 0 and low > 0:
                        margin = (high - low) / low * 100
                        avg_price = (high + low) / 2  # Use average of high/low as "price"
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        hour = dt.hour

                        # Check if in post-breach window
                        is_post = any(bh <= hour < bh + 2 for bh in BREACH_HOURS_UTC)

                        if is_post:
                            post_margins.append(margin)
                            post_prices.append(avg_price)
                        else:
                            other_margins.append(margin)
                            other_prices.append(avg_price)

                if post_margins and other_margins and post_prices and other_prices:
                    avg_post_margin = sum(post_margins) / len(post_margins)
                    avg_other_margin = sum(other_margins) / len(other_margins)
                    margin_boost = avg_post_margin - avg_other_margin

                    avg_post_price = sum(post_prices) / len(post_prices)
                    avg_other_price = sum(other_prices) / len(other_prices)
                    price_change_pct = ((avg_post_price - avg_other_price) / avg_other_price) * 100 if avg_other_price > 0 else 0

                    # Include if margin boost > 2% OR price change > 2%
                    if margin_boost > 2 or abs(price_change_pct) > 2:
                        results.append({
                            'item_id': item_id,
                            'margin_boost': margin_boost,
                            'post_margin': avg_post_margin,
                            'other_margin': avg_other_margin,
                            'price_change_pct': price_change_pct,
                            'post_price': avg_post_price,
                            'other_price': avg_other_price,
                            # Keep 'boost' for backwards compatibility
                            'boost': margin_boost
                        })
            except:
                pass

        return sorted(results, key=lambda x: -x['margin_boost'])[:10]
    except:
        return []

# === CONFIG ===
API_BASE = "https://prices.runescape.wiki/api/v1/dmm"
HEADERS = {"User-Agent": "DMM-Flip-Tracker/2026"}
HISTORY_FILE = "price_history.json"  # Shared - everyone benefits
ALERTS_FILE = "price_alerts.json"  # Persistent alerts
POSITIONS_FILE = "ge_positions.json"  # Persistent GE offers
SETTINGS_FILE = "user_settings.json"  # Persistent settings (capital, nickname, etc.)
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

    /* === FADE IN ANIMATIONS === */
    .main .block-container {
        animation: fadeSlideIn 0.5s ease-out;
    }
    @keyframes fadeSlideIn {
        from {
            opacity: 0;
            transform: translateY(10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    /* Staggered fade for metrics */
    [data-testid="stMetric"] {
        animation: fadeScale 0.4s ease-out backwards;
    }
    [data-testid="stHorizontalBlock"] > div:nth-child(1) [data-testid="stMetric"] { animation-delay: 0.05s; }
    [data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetric"] { animation-delay: 0.1s; }
    [data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetric"] { animation-delay: 0.15s; }
    [data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetric"] { animation-delay: 0.2s; }
    [data-testid="stHorizontalBlock"] > div:nth-child(5) [data-testid="stMetric"] { animation-delay: 0.25s; }

    @keyframes fadeScale {
        from {
            opacity: 0;
            transform: scale(0.95);
        }
        to {
            opacity: 1;
            transform: scale(1);
        }
    }

    /* Dataframes fade in */
    [data-testid="stDataFrame"] {
        animation: fadeSlideUp 0.5s ease-out 0.2s backwards;
    }
    @keyframes fadeSlideUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    /* Headers glow in */
    h1, h2, h3, .stSubheader {
        animation: glowIn 0.6s ease-out;
    }
    @keyframes glowIn {
        from {
            opacity: 0;
            text-shadow: 0 0 0 rgba(212, 175, 55, 0);
        }
        to {
            opacity: 1;
            text-shadow: 0 0 20px rgba(212, 175, 55, 0.3);
        }
    }

    /* Menu bar slide down */
    .menu-bar {
        animation: slideDown 0.3s ease-out;
    }
    @keyframes slideDown {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
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

@st.cache(ttl=30, allow_output_mutation=True)
def fetch_prices():
    resp = requests.get(f"{API_BASE}/latest", headers=HEADERS)
    return resp.json()['data']

@st.cache(ttl=30, allow_output_mutation=True)
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

# === DATA FUNCTIONS (persistent files + session state) ===
def load_positions():
    """Load GE positions from persistent file - always reload"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, 'r') as f:
                file_positions = json.load(f)
                if not st.session_state.get('positions'):
                    st.session_state['positions'] = file_positions
        except:
            if 'positions' not in st.session_state:
                st.session_state['positions'] = []
    elif 'positions' not in st.session_state:
        st.session_state['positions'] = []
    return st.session_state.get('positions', [])

def save_positions(positions):
    """Save GE positions to persistent file"""
    st.session_state['positions'] = positions
    try:
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
    except Exception as e:
        st.warning(f"Could not save positions: {e}")
    auto_save()

def load_alerts():
    """Load alerts from persistent file - always reload from file"""
    # Always try to load from file first (handles meta refresh)
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, 'r') as f:
                file_alerts = json.load(f)
                # Merge with session state (file takes precedence if session is empty)
                if not st.session_state.get('alerts'):
                    st.session_state['alerts'] = file_alerts
        except:
            if 'alerts' not in st.session_state:
                st.session_state['alerts'] = []
    elif 'alerts' not in st.session_state:
        st.session_state['alerts'] = []
    return st.session_state.get('alerts', [])

def save_alerts(alerts):
    """Save alerts to persistent file"""
    st.session_state['alerts'] = alerts
    try:
        with open(ALERTS_FILE, 'w') as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        st.warning(f"Could not save alerts: {e}")
    auto_save()

def load_settings():
    """Load user settings (capital, nickname, etc.) from persistent file - always reload"""
    # Always try to load from file (handles meta refresh)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Only load if session_state doesn't have values yet
                if 'capital' not in st.session_state or st.session_state.get('capital') == 50000:
                    st.session_state['capital'] = settings.get('capital', 50000)
                if 'nickname' not in st.session_state or st.session_state.get('nickname') == '':
                    st.session_state['nickname'] = settings.get('nickname', '')
                if 'min_margin' not in st.session_state:
                    st.session_state['min_margin'] = settings.get('min_margin', 3)
                if 'max_margin' not in st.session_state:
                    st.session_state['max_margin'] = settings.get('max_margin', 30)
                if 'filter_stale' not in st.session_state:
                    st.session_state['filter_stale'] = settings.get('filter_stale', True)
                if 'filter_low_vol' not in st.session_state:
                    st.session_state['filter_low_vol'] = settings.get('filter_low_vol', True)
        except:
            pass
    return {
        'capital': st.session_state.get('capital', 50000),
        'nickname': st.session_state.get('nickname', ''),
        'min_margin': st.session_state.get('min_margin', 3),
        'max_margin': st.session_state.get('max_margin', 30),
        'filter_stale': st.session_state.get('filter_stale', True),
        'filter_low_vol': st.session_state.get('filter_low_vol', True)
    }

def save_settings(capital=None, nickname=None, min_margin=None, max_margin=None, filter_stale=None, filter_low_vol=None):
    """Save user settings to persistent file"""
    if capital is not None:
        st.session_state['capital'] = capital
    if nickname is not None:
        st.session_state['nickname'] = nickname
    if min_margin is not None:
        st.session_state['min_margin'] = min_margin
    if max_margin is not None:
        st.session_state['max_margin'] = max_margin
    if filter_stale is not None:
        st.session_state['filter_stale'] = filter_stale
    if filter_low_vol is not None:
        st.session_state['filter_low_vol'] = filter_low_vol

    settings = {
        'capital': st.session_state.get('capital', 50000),
        'nickname': st.session_state.get('nickname', ''),
        'min_margin': st.session_state.get('min_margin', 3),
        'max_margin': st.session_state.get('max_margin', 30),
        'filter_stale': st.session_state.get('filter_stale', True),
        'filter_low_vol': st.session_state.get('filter_low_vol', True)
    }
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except:
        pass

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
        if col in ['Buy', 'Sell', 'Profit', 'Vol/hr', 'GP/hr', '💰GP/hr', 'Locked', 'My Price', 'Market High', 'Market Low', 'Current High', 'Current Low', 'Diff', 'Target/hr', 'Done', '💎Potential']:
            format_dict[col] = '{:,.0f}'
        elif col in ['Margin %']:
            format_dict[col] = '{:.2f}%'  # Add % symbol
        elif col in ['🔥Agg', '⚖️Bal', '🛡️Con', 'Stab', 'Qty', '#', '💎Score']:
            format_dict[col] = '{:.0f}'
        elif col in ['ROI %']:
            format_dict[col] = '{:.1f}%'

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

def find_high_ticket_items(items, prices, volumes, capital, min_margin=3):
    """
    Find ALL high-value items (top 25% by price) and assess their flip potential.

    Returns both flippable items AND filtered items with reasons, so nothing is hidden.
    """
    import math

    # Calculate dynamic price threshold (75th percentile of all tradeable items)
    all_prices = []
    for item_id_str, p in prices.items():
        high = p.get('high')
        if high and high > 0:
            all_prices.append(high)

    if not all_prices:
        return [], [], 0, {}

    # Dynamic threshold: 75th percentile (top 25%)
    price_threshold = np.percentile(all_prices, 75)

    high_ticket = []      # Items good for flipping
    filtered_items = []   # Items filtered out (with reasons)
    no_data_items = []    # Rare items with no price data
    filter_stats = {
        'total_above_threshold': 0,
        'no_valid_prices': 0,
        'stale_prices': 0,
        'bad_spread': 0,
        'cant_afford': 0,
        'no_volume': 0,
        'low_margin': 0,
        'cant_buy_any': 0,
        'no_price_data': 0,
        'passed': 0
    }

    now = int(time.time())

    # Track which items have price data
    items_with_prices = set(int(k) for k in prices.keys())

    # First, find rare items (low GE limit) that have NO price data at all
    for item_id, item in items.items():
        if item_id in items_with_prices:
            continue  # Will be processed below

        # Low GE limit suggests rare/expensive item
        if item['limit'] <= 8:
            filter_stats['no_price_data'] += 1
            no_data_items.append({
                'name': item['name'],
                'limit': item['limit'],
                'buy': None,
                'sell': None,
                'margin_pct': 0,
                'volume': 0,
                'age': 9999,
                'reasons': ["📭 No GE trades - check in-game"]
            })

    # Now process items WITH price data
    for item_id_str, p in prices.items():
        item_id = int(item_id_str)
        if item_id not in items:
            continue

        item = items[item_id]
        api_high, api_low = p.get('high'), p.get('low')
        high_time, low_time = p.get('highTime'), p.get('lowTime')

        # Handle inverted prices (API sometimes has high < low)
        # For flipping: buy at lower price, sell at higher price
        if api_high and api_low:
            high = max(api_high, api_low)  # Sell price
            low = min(api_high, api_low)   # Buy price
        else:
            high, low = api_high, api_low

        # Skip items below threshold (use max price)
        max_price = max(api_high or 0, api_low or 0)
        if not max_price or max_price < price_threshold:
            continue

        filter_stats['total_above_threshold'] += 1

        # Track filter reasons - VERY relaxed for high ticket
        # High ticket items trade infrequently, so we accept older data
        filter_reasons = []

        if not all([high, low, high_time, low_time]):
            filter_stats['no_valid_prices'] += 1
            filter_reasons.append("❌ No valid price data")

        age = max(now - high_time, now - low_time) if high_time and low_time else 9999

        # HIGH TICKET: Allow up to 24 HOURS old - these items trade infrequently!
        if age > 86400:  # 24 hours
            filter_stats['stale_prices'] += 1
            filter_reasons.append(f"⏰ Very stale ({age//3600}h old)")

        spread_ratio = high / low if low and low > 0 else 999
        if spread_ratio > 2.5:  # Relaxed for high ticket (wider spreads = more profit)
            filter_stats['bad_spread'] += 1
            filter_reasons.append(f"📊 Wide spread ({spread_ratio:.1f}x)")

        if high and high > capital:
            filter_stats['cant_afford'] += 1
            filter_reasons.append(f"💰 Can't afford ({high:,} > {capital:,})")

        vol = volumes.get(item_id_str, {})
        api_vol = (vol.get('highPriceVolume', 0) or 0) + (vol.get('lowPriceVolume', 0) or 0)

        # SMART VOLUME: If API says 0 but timestamp is recent, it DID trade
        # The volume API might not have the item, but price timestamps prove trades happened
        if api_vol == 0 and age < 3600:
            # Traded in last hour but volume API doesn't have it - infer at least 1
            inferred_vol = 1
            vol_display = "1+"  # Show it traded but exact count unknown
        elif api_vol == 0:
            inferred_vol = 0
            vol_display = "0"
        else:
            inferred_vol = api_vol
            vol_display = str(api_vol)

        total_vol = inferred_vol  # Use for calculations

        margin = high - low - int(high * 0.01) if high and low else 0
        margin_pct = (margin / low * 100) if low and low > 0 else 0

        # HIGH TICKET: Lower margin threshold (2% min) - big items = big profit even at low %
        if margin_pct < 2 and not filter_reasons:
            filter_stats['low_margin'] += 1
            filter_reasons.append(f"📉 Low margin ({margin_pct:.1f}%)")

        max_qty = min(capital // high, item['limit']) if high > 0 and high <= capital else 0

        if max_qty < 1 and high and high <= capital and not filter_reasons:
            filter_stats['cant_buy_any'] += 1
            filter_reasons.append("🚫 Can't buy any (limit issue)")

        # If any critical filters failed, add to filtered list
        if filter_reasons:
            filtered_items.append({
                'name': item['name'],
                'buy': high,
                'sell': low,
                'margin_pct': round(margin_pct, 1),
                'volume': total_vol,
                'age': age,
                'reasons': filter_reasons
            })
            continue

        filter_stats['passed'] += 1

        # === CORE FLIP METRICS ===
        profit_per_cycle = margin * max_qty
        capital_locked = high * max_qty
        roi_pct = (profit_per_cycle / capital_locked) * 100 if capital_locked > 0 else 0
        effective_vol = min(total_vol, item['limit'])
        gp_per_hour = profit_per_cycle * (effective_vol / max(max_qty, 1))

        # === RISK ASSESSMENT ===
        risk_factors = []
        # === RISK ASSESSMENT (relaxed for high ticket) ===
        risk_factors = []
        if total_vol == 0:
            risk_factors.append("📉NoVol")
        if age > 3600:  # 1 hour (not 5 min like regular items)
            risk_factors.append("⏰Old")
        if spread_ratio > 1.5:
            risk_factors.append("📊Spread")

        risk_level = len(risk_factors)
        if risk_level == 0:
            risk_indicator = "✅Fresh"
        elif risk_level == 1:
            risk_indicator = "⚠️" + risk_factors[0]
        else:
            risk_indicator = "🔴Risky"

        # === FLIP SCORE (optimized for HIGH TICKET) ===
        # Prioritize RAW PROFIT over volume - these items trade slowly but profit big

        # Freshness: hours-based for high ticket
        if age < 300:        # < 5 min
            fresh_mult = 1.0
        elif age < 1800:     # < 30 min
            fresh_mult = 0.9
        elif age < 3600:     # < 1 hour
            fresh_mult = 0.8
        elif age < 14400:    # < 4 hours
            fresh_mult = 0.6
        else:                # 4-24 hours
            fresh_mult = 0.4

        # Volume: any volume is good for high ticket
        vol_confidence = 1.0 if total_vol > 0 else 0.5  # Has traded vs hasn't

        # RAW PROFIT is king for high ticket (not GP/hr)
        raw_profit_score = min(100, profit_per_cycle / 5000)  # 500k profit = max
        roi_score = min(100, roi_pct * 10)
        fresh_score = fresh_mult * 100
        vol_score = vol_confidence * 100

        # High ticket score: profit > ROI > freshness > volume
        flip_score = int(
            raw_profit_score * 0.40 +  # 40% raw profit (high ticket = big margins)
            roi_score * 0.25 +          # 25% ROI efficiency
            fresh_score * 0.25 +        # 25% freshness
            vol_score * 0.10            # 10% volume (less important)
        )
        flip_score = int(flip_score * (1 - risk_level * 0.1))  # Smaller risk penalty

        # Format last traded time
        if age < 60:
            last_traded = "just now"
        elif age < 3600:
            last_traded = f"{age//60}m ago"
        else:
            last_traded = f"{age//3600}h ago"

        high_ticket.append({
            'id': item_id,
            'name': item['name'],
            'buy': high,
            'sell': low,
            'margin': margin,
            'margin_pct': margin_pct,
            'volume': total_vol,
            'vol_display': vol_display,  # "1+" if inferred, actual number otherwise
            'profit': profit_per_cycle,
            'qty': max_qty,
            'age': age,
            'limit': item['limit'],
            'gp_per_hour': int(gp_per_hour) if total_vol > 0 else 0,
            'roi_pct': round(roi_pct, 1),
            'capital_locked': capital_locked,
            'flip_score': flip_score,
            'risk': risk_indicator,
            'last_traded': last_traded
        })

    high_ticket.sort(key=lambda x: x['flip_score'], reverse=True)
    filtered_items.sort(key=lambda x: x['buy'], reverse=True)

    return high_ticket, filtered_items, no_data_items, int(price_threshold), filter_stats

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

# === LOAD PERSISTENT SETTINGS ===
saved_settings = load_settings()

# === SIDEBAR ===
st.sidebar.title("💰 DMM Tracker")
st.sidebar.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

if st.sidebar.button("🔄 Refresh"):
    st.cache.clear()
    rerun()

# === USER NICKNAME (for saving/loading data) ===
st.sidebar.markdown("---")
st.sidebar.subheader("👤 Your Profile")
nickname_input = st.sidebar.text_input("Nickname", value=saved_settings['nickname'])

if nickname_input != saved_settings['nickname']:
    save_settings(nickname=nickname_input)

if saved_settings['nickname']:
    st.sidebar.success(f"👤 **{saved_settings['nickname']}** (auto-saving)")

st.sidebar.markdown("---")
capital = st.sidebar.number_input("💵 Your Capital (GP)", value=saved_settings['capital'], min_value=1000, step=10000)
if capital != saved_settings['capital']:
    save_settings(capital=capital)

min_margin = st.sidebar.slider("Min Margin %", 1, 20, saved_settings['min_margin'])
if min_margin != saved_settings['min_margin']:
    save_settings(min_margin=min_margin)

max_margin = st.sidebar.slider("Max Margin %", 10, 50, saved_settings['max_margin'])
if max_margin != saved_settings['max_margin']:
    save_settings(max_margin=max_margin)

st.sidebar.markdown("---")
st.sidebar.subheader("🔧 Filters")
filter_stale = st.sidebar.checkbox("Filter stale prices (>10 min)", value=saved_settings['filter_stale'])
if filter_stale != saved_settings['filter_stale']:
    save_settings(filter_stale=filter_stale)

filter_low_vol = st.sidebar.checkbox("Filter low volume (<5/hr)", value=saved_settings['filter_low_vol'])
if filter_low_vol != saved_settings['filter_low_vol']:
    save_settings(filter_low_vol=filter_low_vol)

st.sidebar.caption("Settings auto-save and persist across refreshes!")

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 Auto-Refresh")

# Initialize defaults in session_state (use widget keys directly)
if 'auto_refresh_on' not in st.session_state:
    st.session_state['auto_refresh_on'] = True  # Default ON

if 'refresh_secs' not in st.session_state:
    st.session_state['refresh_secs'] = 60

# Widgets without key - use value from session_state, update on change
auto_refresh = st.sidebar.checkbox("Enable auto-refresh", value=st.session_state['auto_refresh_on'])
st.session_state['auto_refresh_on'] = auto_refresh

interval_options = [30, 60, 120, 300]
current_interval = st.session_state['refresh_secs']
interval_idx = interval_options.index(current_interval) if current_interval in interval_options else 1
refresh_interval = st.sidebar.selectbox("Refresh every", interval_options, index=interval_idx, format_func=lambda x: f"{x} seconds")
st.session_state['refresh_secs'] = refresh_interval

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
high_ticket_items, filtered_high_ticket, no_data_rare_items, price_threshold, ht_filter_stats = find_high_ticket_items(items, prices, volumes, capital, min_margin)
positions = load_positions()
price_alerts = load_alerts()

# === MENU BAR ===
if 'view' not in st.session_state:
    st.session_state['view'] = 'dashboard'

current_view = st.session_state.get('view', 'dashboard')

# Tab navigation buttons (simple and visible)
col1, col2 = st.columns(2)
with col1:
    dash_label = "● 📊 Dashboard" if current_view == 'dashboard' else "📊 Dashboard"
    if st.button(dash_label, key="tab_dash"):
        st.session_state['view'] = 'dashboard'
        rerun()
with col2:
    plan_label = "● 📋 Smart Planner" if current_view == 'planner' else "📋 Smart Planner"
    if st.button(plan_label, key="tab_plan"):
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

# === QUICK PRICE ALERT (Top of page) ===
with st.expander("🔔 Quick Price Alert - Click to add alerts", expanded=False):
    st.caption("Get notified when prices hit your targets")

    col_search, col_type, col_price, col_btn = st.columns([3, 2, 2, 1])

    with col_search:
        main_alert_search = st.text_input("🔍 Search item", key="main_alert_search")

    main_alert_item = None
    main_alert_item_id = None
    main_curr_high = 0
    main_curr_low = 0

    if main_alert_search and data_ok:
        main_alert_matching = [n for n in item_names.keys() if main_alert_search.lower() in n][:8]
        if main_alert_matching:
            main_alert_item = st.selectbox("Select item", main_alert_matching, key="main_alert_select")

            if main_alert_item:
                main_alert_item_id = item_names[main_alert_item]
                main_ap = prices.get(str(main_alert_item_id), {})
                main_curr_high = main_ap.get('high', 0)
                main_curr_low = main_ap.get('low', 0)
                st.info(f"**{main_alert_item}** — High: **{main_curr_high:,}** | Low: **{main_curr_low:,}**")

    if main_alert_item:
        with col_type:
            main_alert_type = st.selectbox("Alert when", ["High ≥", "High ≤", "Low ≥", "Low ≤"], key="main_alert_type")

        with col_price:
            # Auto-fill based on alert type
            if "High" in main_alert_type:
                suggested_price = main_curr_high
            else:
                suggested_price = main_curr_low
            suggested_price = max(1, suggested_price)

            main_alert_price = st.number_input("Target price", value=suggested_price, min_value=1, key="main_alert_price")

        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)  # Spacing to align button
            add_clicked = st.button("🔔 Add Alert", key="main_add_alert")

            if add_clicked:
                alerts_list = load_alerts()
                new_alert = {
                    'item': items[main_alert_item_id]['name'],
                    'item_id': main_alert_item_id,
                    'enabled': True
                }
                if main_alert_type == "High ≥":
                    new_alert['high_above'] = int(main_alert_price)
                elif main_alert_type == "High ≤":
                    new_alert['high_below'] = int(main_alert_price)
                elif main_alert_type == "Low ≥":
                    new_alert['low_above'] = int(main_alert_price)
                elif main_alert_type == "Low ≤":
                    new_alert['low_below'] = int(main_alert_price)

                alerts_list.append(new_alert)
                save_alerts(alerts_list)
                st.success(f"✅ Alert added: {main_alert_item} when {main_alert_type} {main_alert_price:,}")
                rerun()

st.markdown("---")

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

    # === BREACH COUNTDOWN ===
    breach_info = get_breach_info()

    if breach_info['in_post_breach']:
        # We're in a post-breach window - show prominent alert with scan button
        breach_col1, breach_col2 = st.columns([4, 1])
        with breach_col1:
            st.markdown(f"""
            <div style="background: linear-gradient(90deg, #FF4757 0%, #FF6B7A 100%);
                        padding: 15px 20px; border-radius: 10px; margin: 15px 0;
                        border: 2px solid #FF4757; text-align: center;">
                <span style="font-size: 1.5rem; font-weight: bold; color: white;">
                    ⚔️ POST-BREACH MODE ACTIVE ⚔️
                </span>
                <br>
                <span style="color: #FFE0E0; font-size: 1rem;">
                    Breach at {breach_info['current_breach_pacific']} PT ended recently — Margins boosted on restocking items!
                </span>
            </div>
            """, unsafe_allow_html=True)
        with breach_col2:
            st.write("")  # Spacer
            if st.button("🔍 Scan Items", key="breach_scan_active"):
                with st.spinner("Scanning..."):
                    scanned = fetch_breach_scanner_data()
                    if scanned:
                        st.session_state['breach_scan_results'] = scanned
                    else:
                        st.session_state['breach_scan_results'] = []

        # Show scan results if available
        if 'breach_scan_results' in st.session_state and st.session_state['breach_scan_results']:
            scanned = st.session_state['breach_scan_results']
            with st.expander(f"📊 Breach Scan Results ({len(scanned)} items found)", expanded=True):
                st.markdown("""
                <div style="background: #1A1D24; padding: 10px 15px; border-radius: 6px; margin-bottom: 10px; border-left: 3px solid #D4AF37;">
                    <strong style="color: #D4AF37;">What this means:</strong><br>
                    <span style="color: #A0A0A0; font-size: 0.9rem;">
                        After breaches, players restock consumables (food, pots, runes), causing price and margin changes.
                        Data shows behavior in the <strong>0-2 hours after breach</strong> vs normal times.
                    </span>
                </div>
                """, unsafe_allow_html=True)

                scan_data = []
                for item in scanned[:10]:
                    item_name = items.get(item['item_id'], {}).get('name', f"Item {item['item_id']}")
                    price_change = item.get('price_change_pct', 0)
                    price_dir = "+" if price_change >= 0 else ""
                    # Get current price from prices dict
                    curr_price_data = prices.get(str(item['item_id']), {})
                    curr_high = curr_price_data.get('high', 0)
                    curr_low = curr_price_data.get('low', 0)
                    curr_price = (curr_high + curr_low) // 2 if curr_high and curr_low else 0
                    scan_data.append({
                        'Item': item_name,
                        'Current': f"{curr_price:,}" if curr_price else "N/A",
                        'Normal': f"{item.get('other_price', 0):,.0f}",
                        'Post-Breach': f"{item.get('post_price', 0):,.0f}",
                        'Price Δ': f"{price_dir}{price_change:.1f}%",
                        'Margin Boost': f"+{item.get('margin_boost', item['boost']):.1f}%"
                    })

                if scan_data:
                    df = pd.DataFrame(scan_data)
                    # Convert percentage strings to floats for sorting
                    df['_price_sort'] = df['Price Δ'].str.replace('%', '').str.replace('+', '').astype(float)
                    df['_margin_sort'] = df['Margin Boost'].str.replace('%', '').str.replace('+', '').astype(float)
                    df = df.sort_values('_margin_sort', ascending=False).drop(columns=['_price_sort', '_margin_sort'])

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            'Item': st.column_config.TextColumn('Item', width='medium'),
                            'Current': st.column_config.TextColumn('Current', width='small'),
                            'Normal': st.column_config.TextColumn('Normal', width='small'),
                            'Post-Breach': st.column_config.TextColumn('Post-Breach', width='small'),
                            'Price Δ': st.column_config.TextColumn('Price Δ', width='small'),
                            'Margin Boost': st.column_config.TextColumn('Margin Boost', width='small'),
                        }
                    )
                    st.caption("Current = live price now. Normal/Post-Breach = avg prices from last 48hrs. Price Δ = change after breach. Click headers to sort.")

        # Show breach items
        breach_opps = scan_breach_items(prices, volumes, items, item_names)
        if breach_opps:
            st.subheader("🔥 Breach Mode: Best Restock Flips")
            st.caption("These items have historically higher margins after breaches when players restock")

            breach_data = []
            for b in breach_opps:
                breach_data.append({
                    'Item': b['name'],
                    'Buy': b['buy'],
                    'Sell': b['sell'],
                    'Margin %': round(b['margin_pct'], 1),
                    'Vol/hr': b['volume'],
                    'Limit': b['limit'],
                    'Boost': f"+{b['boost']:.0f}%"
                })

            if breach_data:
                df = pd.DataFrame(breach_data)
                styled_df = style_dataframe(df, color_cols=['Margin %', 'Vol/hr'])
                st.dataframe(styled_df)
                st.caption("Boost = historical margin increase during post-breach window")

            st.markdown("---")
    else:
        # Show countdown to next breach with scan button
        hours_until = breach_info['hours_until']
        if hours_until <= 1:
            urgency_color = "#FF4757"  # Red - imminent
            urgency_text = "IMMINENT"
        elif hours_until <= 3:
            urgency_color = "#FFA502"  # Orange - soon
            urgency_text = "SOON"
        else:
            urgency_color = "#00D26A"  # Green - plenty of time
            urgency_text = ""

        breach_col1, breach_col2 = st.columns([4, 1])
        with breach_col1:
            st.markdown(f"""
            <div style="background: var(--bg-card); padding: 12px 20px; border-radius: 8px;
                        margin: 10px 0; border-left: 4px solid {urgency_color};
                        display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #A0A0A0;">
                    ⚔️ Next Breach: <strong style="color: {urgency_color};">{breach_info['next_breach_pacific']} PT</strong>
                    {f' ({urgency_text})' if urgency_text else ''}
                </span>
                <span style="font-size: 1.3rem; font-weight: bold; color: {urgency_color};">
                    {breach_info['countdown']}
                </span>
            </div>
            """, unsafe_allow_html=True)
        with breach_col2:
            st.write("")  # Spacer
            if st.button("🔍 Scan Items", key="breach_scan_countdown"):
                with st.spinner("Scanning..."):
                    scanned = fetch_breach_scanner_data()
                    if scanned:
                        st.session_state['breach_scan_results'] = scanned
                    else:
                        st.session_state['breach_scan_results'] = []

        # Show scan results if available
        if 'breach_scan_results' in st.session_state and st.session_state['breach_scan_results']:
            scanned = st.session_state['breach_scan_results']
            with st.expander(f"📊 Breach Scan Results ({len(scanned)} items found)", expanded=True):
                st.markdown("""
                <div style="background: #1A1D24; padding: 10px 15px; border-radius: 6px; margin-bottom: 10px; border-left: 3px solid #D4AF37;">
                    <strong style="color: #D4AF37;">What this means:</strong><br>
                    <span style="color: #A0A0A0; font-size: 0.9rem;">
                        After breaches, players restock consumables (food, pots, runes), causing price and margin changes.
                        Data shows behavior in the <strong>0-2 hours after breach</strong> vs normal times.
                    </span>
                </div>
                """, unsafe_allow_html=True)

                scan_data = []
                for item in scanned[:10]:
                    item_name = items.get(item['item_id'], {}).get('name', f"Item {item['item_id']}")
                    price_change = item.get('price_change_pct', 0)
                    price_dir = "+" if price_change >= 0 else ""
                    # Get current price from prices dict
                    curr_price_data = prices.get(str(item['item_id']), {})
                    curr_high = curr_price_data.get('high', 0)
                    curr_low = curr_price_data.get('low', 0)
                    curr_price = (curr_high + curr_low) // 2 if curr_high and curr_low else 0
                    scan_data.append({
                        'Item': item_name,
                        'Current': f"{curr_price:,}" if curr_price else "N/A",
                        'Normal': f"{item.get('other_price', 0):,.0f}",
                        'Post-Breach': f"{item.get('post_price', 0):,.0f}",
                        'Price Δ': f"{price_dir}{price_change:.1f}%",
                        'Margin Boost': f"+{item.get('margin_boost', item['boost']):.1f}%"
                    })

                if scan_data:
                    df = pd.DataFrame(scan_data)
                    # Convert percentage strings to floats for sorting
                    df['_price_sort'] = df['Price Δ'].str.replace('%', '').str.replace('+', '').astype(float)
                    df['_margin_sort'] = df['Margin Boost'].str.replace('%', '').str.replace('+', '').astype(float)
                    df = df.sort_values('_margin_sort', ascending=False).drop(columns=['_price_sort', '_margin_sort'])

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            'Item': st.column_config.TextColumn('Item', width='medium'),
                            'Current': st.column_config.TextColumn('Current', width='small'),
                            'Normal': st.column_config.TextColumn('Normal', width='small'),
                            'Post-Breach': st.column_config.TextColumn('Post-Breach', width='small'),
                            'Price Δ': st.column_config.TextColumn('Price Δ', width='small'),
                            'Margin Boost': st.column_config.TextColumn('Margin Boost', width='small'),
                        }
                    )
                    st.caption("Current = live price now. Normal/Post-Breach = avg prices from last 48hrs. Price Δ = change after breach. Click headers to sort.")

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

    # === SECTION: TOP OPPORTUNITIES (First!) ===
    st.subheader("🔥 Top Opportunities")
    if opps:
        st.caption("Live prices • Sorted by 🔥Aggressive • Click column headers to re-sort!")

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

            # Calculate Potential: profit * min(vol/hr, limit) = GP potential per limit cycle
            effective_vol = min(opp['volume'], opp['limit'])
            potential = round(opp['profit'] * effective_vol, 0)

            opp_data.append({
                'Item': opp['name'],
                'Buy': opp['buy'],
                'Sell': opp['sell'],
                'Margin %': round(opp['margin_pct'], 1),
                'Vol/hr': opp['volume'],
                'Fresh': f"{freshness} {format_age(age)}",
                '💎Potential': int(potential),
                'Stab': stab,
                'Trend': trend,
                '🔥Agg': opp['smart_agg'],
                '⚖️Bal': opp['smart_bal'],
                '🛡️Con': opp['smart_con'],
                'Profit': opp['profit']
            })
        df = pd.DataFrame(opp_data)
        styled_df = style_dataframe(df, color_cols=['Profit', 'Vol/hr', '💎Potential', 'Stab', '🔥Agg', '⚖️Bal', '🛡️Con'])
        st.dataframe(styled_df)
        st.caption("💎Potential = Profit × min(Vol,Limit) | Stab=Stability | 🔥Agg | ⚖️Bal | 🛡️Con")
    else:
        st.info("No opportunities with current filters")

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

            # Calculate Potential: profit * min(vol/hr, limit) = GP potential per limit cycle
            item_limit = items.get(s.get('item_id'), {}).get('limit', 1)
            effective_vol = min(s.get('volume', 0), item_limit)
            potential = round(s['profit'] * effective_vol, 0)

            stable_data.append({
                'Item': s['name'],
                'Buy': s['buy'],
                'Sell': s['sell'],
                'Margin %': round(s['margin_pct'], 1),
                'Vol/hr': s.get('volume', 0),
                'Fresh': f"{freshness} {format_age(age)}",
                '💎Potential': int(potential),
                'Stab': s.get('score', 0),
                'Price': s.get('price_trend', '—'),
                'Margin': s.get('margin_trend', '—'),
                '🔥Agg': s.get('smart_agg', 0),
                '⚖️Bal': s.get('smart_bal', 0),
                '🛡️Con': s.get('smart_con', 0),
                'Profit': s['profit']
            })
        df = pd.DataFrame(stable_data)
        styled_df = style_dataframe(df, color_cols=['Profit', 'Vol/hr', '💎Potential', 'Stab', '🔥Agg', '⚖️Bal', '🛡️Con'])
        st.dataframe(styled_df)
        st.caption("💎Potential = Profit × min(Vol,Limit) | Stab=Stability | Price/Margin=Trends")
    else:
        st.info(f"Building data... tracking {len(history)} items. Keep page open!")

    st.markdown("---")

    # === SECTION: HIGH TICKET ITEMS ===
    st.subheader("💰 High Ticket Flips")

    # Item lookup - find any item and see why it's not showing
    with st.expander("🔍 Look up a specific item"):
        search_item = st.text_input("Item name", placeholder="e.g., Twinflame staff", key="ht_search")
        if search_item:
            search_lower = search_item.lower()
            found_id = item_names.get(search_lower)

            if found_id:
                item_info = items.get(found_id, {})
                price_data = prices.get(str(found_id), {})
                vol_data = volumes.get(str(found_id), {})

                st.markdown(f"### {item_info.get('name', search_item)}")

                if price_data:
                    api_high = price_data.get('high', 0)
                    api_low = price_data.get('low', 0)
                    high_time = price_data.get('highTime', 0)
                    low_time = price_data.get('lowTime', 0)
                    now = int(time.time())
                    age = max(now - high_time, now - low_time) if high_time and low_time else 9999

                    # For FLIPPING: you BUY at low price, SELL at high price
                    # API can sometimes have inverted data, so use min/max
                    buy_price = min(api_high, api_low) if api_high and api_low else 0
                    sell_price = max(api_high, api_low) if api_high and api_low else 0

                    vol = (vol_data.get('highPriceVolume', 0) or 0) + (vol_data.get('lowPriceVolume', 0) or 0)

                    # Margin = sell - buy - 1% tax (on sell price)
                    margin = sell_price - buy_price - int(sell_price * 0.01) if buy_price and sell_price else 0
                    margin_pct = (margin / buy_price * 100) if buy_price else 0

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Buy At", f"{buy_price:,}" if buy_price else "N/A")
                    col2.metric("Sell At", f"{sell_price:,}" if sell_price else "N/A")
                    col3.metric("Margin", f"{margin_pct:.1f}%" if margin_pct else "N/A")

                    col4, col5, col6 = st.columns(3)
                    col4.metric("Vol/hr", vol)
                    col5.metric("GE Limit", item_info.get('limit', '?'))
                    if age < 3600:
                        col6.metric("Last Trade", f"{age//60}m ago")
                    elif age < 86400:
                        col6.metric("Last Trade", f"{age//3600}h ago")
                    else:
                        col6.metric("Last Trade", f"{age//86400}d ago")

                    # Show WHY it's not in high ticket
                    st.markdown("**Why not showing in High Ticket:**")
                    reasons = []
                    max_price = max(api_high, api_low) if api_high and api_low else 0
                    if max_price and max_price < price_threshold:
                        reasons.append(f"❌ Price ({max_price:,}) below threshold ({price_threshold:,})")
                    if age > 86400:
                        reasons.append(f"❌ Too stale ({age//3600}h old, max 24h)")
                    if buy_price and buy_price > capital:
                        reasons.append(f"❌ Can't afford ({buy_price:,} > {capital:,})")
                    if margin_pct < 2:
                        reasons.append(f"❌ Low margin ({margin_pct:.1f}%, min 2%)")
                    spread = sell_price / buy_price if buy_price else 999
                    if spread > 2.5:
                        reasons.append(f"❌ Wide spread ({spread:.1f}x, max 2.5x)")

                    if not reasons:
                        st.success("✅ Should be showing! Check the table below.")
                    else:
                        for r in reasons:
                            st.warning(r)
                else:
                    st.error(f"📭 No GE price data for this item")
                    st.info(f"GE Limit: {item_info.get('limit', '?')} - This item hasn't traded on the GE recently.")
            else:
                # Fuzzy match suggestions
                matches = [name for name in item_names.keys() if search_lower in name][:5]
                if matches:
                    st.warning(f"Item not found. Did you mean: {', '.join(matches)}?")
                else:
                    st.error("Item not found in database")

    # Show stats about coverage
    total_ht = ht_filter_stats.get('total_above_threshold', 0)
    passed_ht = ht_filter_stats.get('passed', 0)
    st.caption(f"📊 **{passed_ht}/{total_ht}** items above {price_threshold:,} gp are flippable right now")

    if high_ticket_items:
        high_ticket_data = []
        for item in high_ticket_items:
            # Freshness indicator (hours-based for high ticket)
            age = item['age']
            if age < 300:        # < 5 min
                freshness = "🟢"
            elif age < 1800:     # < 30 min
                freshness = "🟢"
            elif age < 3600:     # < 1 hour
                freshness = "🟡"
            elif age < 14400:    # < 4 hours
                freshness = "🟠"
            else:
                freshness = "🔴"

            high_ticket_data.append({
                'Item': item['name'],
                '💎Score': item['flip_score'],
                'Profit': item['profit'],  # Raw profit per flip (key for high ticket!)
                'ROI %': item['roi_pct'],
                'Buy': item['buy'],
                'Sell': item['sell'],
                'Margin %': round(item['margin_pct'], 1),
                'Vol': item['vol_display'],  # "1+" if inferred from timestamp
                'Last Trade': f"{freshness} {item['last_traded']}",
                'Risk': item['risk'],
                'Locked': item['capital_locked']
            })
        df = pd.DataFrame(high_ticket_data)
        styled_df = style_dataframe(df, color_cols=['💎Score', 'Profit', 'ROI %'])
        st.dataframe(styled_df)
        st.caption("💎Score = Profit × ROI × Freshness | Vol = trades/hr (1+ = traded recently but count unknown)")
    else:
        st.info("No high ticket items currently flippable")

    # Show filtered items so nothing is hidden
    total_filtered = len(filtered_high_ticket) + len(no_data_rare_items)
    if total_filtered > 0:
        with st.expander(f"👁️ View {total_filtered} filtered/rare items (why they're excluded)"):
            # Show filter breakdown
            cols = st.columns(4)
            cols[0].metric("⏰ Very Stale (24h+)", ht_filter_stats.get('stale_prices', 0))
            cols[1].metric("💰 Can't Afford", ht_filter_stats.get('cant_afford', 0))
            cols[2].metric("📊 Bad Spread", ht_filter_stats.get('bad_spread', 0))
            cols[3].metric("📭 No GE Data", ht_filter_stats.get('no_price_data', 0))

            # Show filtered items with price data
            if filtered_high_ticket:
                st.markdown("##### 📊 Filtered (have prices, don't meet criteria)")
                filtered_data = []
                for item in filtered_high_ticket[:15]:
                    reasons_str = " | ".join(item['reasons'][:2])
                    filtered_data.append({
                        'Item': item['name'],
                        'Buy': item['buy'] if item['buy'] else '—',
                        'Sell': item['sell'] if item['sell'] else '—',
                        'Margin %': item['margin_pct'],
                        'Vol/hr': item['volume'],
                        'Why': reasons_str
                    })
                if filtered_data:
                    fdf = pd.DataFrame(filtered_data)
                    st.dataframe(fdf, use_container_width=True)

            # Show rare items with NO price data (like Statius warhammer)
            if no_data_rare_items:
                st.markdown("##### 📭 Rare Items (no GE data - check in-game)")
                st.caption(f"These {len(no_data_rare_items)} items have low GE limits (rare/expensive) but no recent trades on the GE API")
                rare_data = []
                for item in no_data_rare_items[:20]:
                    rare_data.append({
                        'Item': item['name'],
                        'GE Limit': item['limit'],
                        'Status': '📭 No trades'
                    })
                if rare_data:
                    rdf = pd.DataFrame(rare_data)
                    st.dataframe(rdf, use_container_width=True)
                st.caption("💡 These items may still be tradeable - check World 2 GE or trade in person!")

    st.markdown("---")
    st.caption(f"Data: {len(history)} items tracked | {sum(len(h) for h in history.values())} samples | Synced with notebook")

# === AUTO-REFRESH ===
if auto_refresh:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)
    st.caption(f"🔄 Auto-refreshing every {refresh_interval}s (state resets on refresh - this is normal)")
