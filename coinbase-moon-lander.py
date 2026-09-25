import streamlit as st
import pandas as pd
import time
import os
import logging
import random
from decimal import Decimal
from datetime import datetime
from dotenv import load_dotenv
import textwrap

# --- 1. Configuration & Setup ---

st.set_page_config(
    page_title="Coinbase Market Kombat", 
    page_icon="🥊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configure Logging
logging.basicConfig(level=logging.CRITICAL)
try:
    logging.getLogger('coinbase.RESTClient').setLevel(logging.CRITICAL)
except:
    pass

# Try to import Coinbase SDK
COINBASE_SDK_AVAILABLE = False
try:
    from coinbase.rest import RESTClient
    COINBASE_SDK_AVAILABLE = True
except ImportError:
    pass

# --- 2. Sidebar Controls & Mode Selection ---

st.sidebar.markdown("## 🥊 MARKET KOMBAT")
st.sidebar.caption("Retro Arcade Order Book Combat Engine")

# Auto-detect if credentials exist in env
script_dir = os.path.dirname(os.path.abspath(__file__))
for path in [os.path.join(script_dir, '.env'), 
             os.path.join(script_dir, '../.env'), 
             os.path.join(script_dir, '../../.env')]:
    if os.path.exists(path):
        load_dotenv(dotenv_path=path)
        break

env_has_keys = bool(os.getenv('CB_API_KEY') and os.getenv('CB_API_SECRET'))

# Toggle for Demo Arena
default_demo = not env_has_keys and ('api_key' not in st.session_state)
demo_mode = st.sidebar.checkbox("🕹️ Arcade Demo Mode", value=st.session_state.get('demo_mode', default_demo))
st.session_state.demo_mode = demo_mode

auto_refresh = st.sidebar.checkbox("⚡ Auto-refresh (30s)", value=True)
sound_fx_hint = st.sidebar.checkbox("🔊 Retro FX Vibes", value=True)

if st.sidebar.button("🔄 Trigger Next Tick"):
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Combat Rules**:
* **The Bull [Long]**: Your active trade.
* **The Bear [Boss]**: Market resistance / Take Profit target.
* **Fireballs (Asks)**: Resistance walls hurled by Bear.
* **Shields (Bids)**: Support orders defending Bull.
* **Lifebars**: Health 100% = TP strike; 0% = SL crash.
""")

# --- 3. Auth Logic (with Demo Fallback) ---

def get_api_client():
    if demo_mode:
        return None
        
    api_key = os.getenv('CB_API_KEY')
    api_secret = os.getenv('CB_API_SECRET')

    if not api_key or not api_secret:
        try:
            if "CB_API_KEY" in st.secrets:
                api_key = st.secrets["CB_API_KEY"]
            if "CB_API_SECRET" in st.secrets:
                api_secret = st.secrets["CB_API_SECRET"]
        except Exception:
            pass
    
    if not api_key or not api_secret:
        if 'api_key' in st.session_state:
            api_key = st.session_state.api_key
            api_secret = st.session_state.api_secret
        
        if not api_key:
            st.header("🥊 WELCOME TO MARKET KOMBAT")
            st.info("Choose your arena entry: Enter Coinbase API Keys or jump into the **Arcade Demo Arena**.")
            
            col_live, col_demo = st.columns([1, 1])
            with col_demo:
                st.subheader("🕹️ Quick Preview")
                st.write("Instant access to simulated live bouts, projectiles, and K.O. finishes without needing API keys.")
                if st.button("Enter Arcade Demo Arena", type="primary", use_container_width=True):
                    st.session_state.demo_mode = True
                    st.rerun()

            with col_live:
                st.subheader("🔑 Live Coinbase Keys")
                with st.form("creds_form"):
                    k = st.text_input("API Key", type="password")
                    s = st.text_input("API Secret", type="password")
                    
                    is_cloud = bool(
                        os.getenv("STREAMLIT_SHARING_HOST")
                        or os.getenv("IS_STREAMLIT_CLOUD")
                        or os.path.exists("/mount/src")
                        or os.getenv("SPACE_ID")
                    )
                    
                    save_env = st.checkbox("Save credentials to .env (Local Only)") if not is_cloud else False
                    submitted = st.form_submit_button("Engage Live Arena", use_container_width=True)
                    
                    if submitted and k and s:
                        if save_env and not is_cloud:
                            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
                            try:
                                with open(env_path, "a") as f:
                                    f.write(f"\nCB_API_KEY={k}\nCB_API_SECRET={s}\n")
                                st.success("Credentials saved to .env!")
                            except Exception as e:
                                st.error(f"Failed to save .env: {e}")
                        
                        st.session_state.api_key = k
                        st.session_state.api_secret = s
                        st.session_state.demo_mode = False
                        st.rerun()

            st.stop()
            return None

    if not COINBASE_SDK_AVAILABLE:
        st.error("Missing `coinbase-advanced-py` package. Run `pip install coinbase-advanced-py`.")
        st.stop()

    return RESTClient(api_key=api_key, api_secret=api_secret)

# --- 4. Live Backend Logic ---

def get_best_bid(client, product_id):
    if not client: return None
    try:
        ticker = client.get_product_book(product_id=product_id, limit=1)
        if ticker and hasattr(ticker, 'pricebook') and hasattr(ticker.pricebook, 'bids') and len(ticker.pricebook.bids) > 0:
             return Decimal(str(ticker.pricebook.bids[0].price))
    except Exception:
        pass
    return None

def get_asset_price(client, asset):
    if asset in ['USD', 'USDC']: return Decimal('1.0')
    price = get_best_bid(client, f"{asset}-USD")
    if price is None:
        price = get_best_bid(client, f"{asset}-USDC")
    return price

def get_market_depth(client, product_id):
    if not client: return None
    try:
        return client.get_product_book(product_id=product_id, limit=50)
    except Exception:
        return None

def filter_spaced_items(items, target_count=6, min_dist=12):
    sorted_items = sorted(items, key=lambda x: x['raw_size'], reverse=True)
    kept = []
    taken_positions = []
    for item in sorted_items:
        if len(kept) >= target_count: break
        pct = item['pct']
        is_too_close = any(abs(p - pct) < min_dist for p in taken_positions)
        if not is_too_close:
            kept.append(item)
            taken_positions.append(pct)
    return kept

def get_open_orders_data(client):
    if not client: return []
    try:
        orders_gen = client.list_orders(order_status=["OPEN"]) 
        orders = orders_gen.orders if hasattr(orders_gen, 'orders') else list(orders_gen)
        if not orders: return []

        orders_data = []
        product_ids = list(set([getattr(o, 'product_id', '') for o in orders if getattr(o, 'product_id', '')]))
        depth_map = {pid: get_market_depth(client, pid) for pid in product_ids if pid}

        for o in orders:
            pid = getattr(o, 'product_id', 'N/A')
            side = getattr(o, 'side', 'N/A')
            oconf = getattr(o, 'order_configuration', None)
            
            tp_price_dec = Decimal('0')
            sl_price_dec = Decimal('0')
            size_dec = Decimal('0')
            current_unit_price = get_asset_price(client, pid.split('-')[0]) or Decimal('0')
            
            if oconf:
                if hasattr(oconf, 'limit_limit_gtc'):
                    c = oconf.limit_limit_gtc
                    tp_price_dec = Decimal(getattr(c, 'limit_price', '0'))
                    size_dec = Decimal(getattr(c, 'base_size', '0'))
                    sl_price_dec = get_asset_price(client, pid.split('-')[0]) or Decimal('0') 
                elif hasattr(oconf, 'trigger_bracket_gtc'):
                     c = oconf.trigger_bracket_gtc
                     limit_price = getattr(c, 'limit_price', None)
                     stop_price = getattr(c, 'stop_trigger_price', None)
                     size_dec = Decimal(getattr(c, 'base_size', '0'))
                     if limit_price: tp_price_dec = Decimal(limit_price)
                     if stop_price: sl_price_dec = Decimal(stop_price)
                elif hasattr(oconf, 'stop_limit_stop_limit_gtc'):
                     c = oconf.stop_limit_stop_limit_gtc
                     stop_price = getattr(c, 'stop_price', None)
                     size_dec = Decimal(getattr(c, 'base_size', '0'))
                     if stop_price: sl_price_dec = Decimal(stop_price)

            health_score = 50
            if tp_price_dec > 0 and sl_price_dec > 0 and current_unit_price > 0:
                try:
                    total_range = tp_price_dec - sl_price_dec
                    if total_range != 0:
                        progress = current_unit_price - sl_price_dec
                        pct = (progress / total_range) * 100
                        health_score = max(0, min(100, int(pct)))
                except: pass
            elif sl_price_dec > 0 and current_unit_price > 0:
                diff = current_unit_price - sl_price_dec
                range_buffer = sl_price_dec * Decimal('0.1') 
                if side == 'SELL':
                    if current_unit_price <= sl_price_dec: health_score = 0
                    else:
                        dist = current_unit_price - sl_price_dec
                        pct = (dist / range_buffer) * 50
                        health_score = 50 + min(50, int(pct))
                else:
                    if current_unit_price >= sl_price_dec: health_score = 100
                    else:
                        dist_to_go = sl_price_dec - current_unit_price
                        pct = (1 - (dist_to_go / range_buffer)) * 100
                        health_score = max(0, min(99, int(pct)))

            fireballs = [] # Resistance / Asks
            shields = []   # Support / Bids
            
            if pid in depth_map and depth_map[pid]:
                book = depth_map[pid]
                if hasattr(book, 'pricebook'):
                    raw_fireballs = []
                    raw_shields = []
                    
                    if hasattr(book.pricebook, 'asks'):
                        for ask in book.pricebook.asks:
                            try:
                                ask_price = Decimal(str(ask.price))
                                ask_size = Decimal(str(ask.size))
                                raw_size = float(ask_size)
                                if ask_price > current_unit_price:
                                    if tp_price_dec > 0 and ask_price > (tp_price_dec * Decimal('1.2')): continue
                                    total_dist = (tp_price_dec - sl_price_dec) if (tp_price_dec > 0 and sl_price_dec > 0) else (sl_price_dec * Decimal('0.1'))
                                    pos_pct = int(((ask_price - sl_price_dec) / total_dist) * 100) if total_dist > 0 else 50
                                    if -10 <= pos_pct <= 120:
                                        val = ask_price * ask_size
                                        raw_fireballs.append({
                                            'price': f"${ask_price:,.2f}",
                                            'size': f"{ask_size}",
                                            'raw_size': raw_size,
                                            'val_fmt': f"${val:,.0f}",
                                            'pct': pos_pct
                                        })
                            except: pass

                    if hasattr(book.pricebook, 'bids'):
                        for bid in book.pricebook.bids:
                            try:
                                bid_price = Decimal(str(bid.price))
                                bid_size = Decimal(str(bid.size))
                                raw_size = float(bid_size)
                                if bid_price < current_unit_price:
                                    if sl_price_dec > 0 and bid_price < (sl_price_dec * Decimal('0.8')): continue
                                    total_dist = (tp_price_dec - sl_price_dec) if (tp_price_dec > 0 and sl_price_dec > 0) else (sl_price_dec * Decimal('0.1'))
                                    pos_pct = int(((bid_price - sl_price_dec) / total_dist) * 100) if total_dist > 0 else 50
                                    if -20 <= pos_pct <= 110:
                                        val = bid_price * bid_size
                                        raw_shields.append({
                                            'price': f"${bid_price:,.2f}",
                                            'size': f"{bid_size}",
                                            'raw_size': raw_size,
                                            'val_fmt': f"${val:,.0f}",
                                            'pct': pos_pct
                                        })
                            except: pass

                    fireballs = filter_spaced_items(raw_fireballs, target_count=8, min_dist=5)
                    shields = filter_spaced_items(raw_shields, target_count=6, min_dist=5)
                    
                    max_size = max([x['raw_size'] for x in fireballs + shields] or [1.0])
                    for f_item in fireballs:
                        r = f_item['raw_size'] / max_size
                        f_item['level'] = 3 if r > 0.6 else (2 if r > 0.2 else 1)
                    for s_item in shields:
                        r = s_item['raw_size'] / max_size
                        s_item['level'] = 3 if r > 0.6 else (2 if r > 0.2 else 1)

            if tp_price_dec > 0 or sl_price_dec > 0:
                est_val_str = f"${size_dec * current_unit_price:,.2f}" if (size_dec > 0 and current_unit_price > 0) else "N/A"
                upside_str = "N/A"
                if tp_price_dec > 0 and size_dec > 0 and current_unit_price > 0:
                    upside = (size_dec * tp_price_dec) - (size_dec * current_unit_price)
                    upside_str = f"{'+' if upside >= 0 else ''}${upside:,.2f}"

                created_time = getattr(o, 'created_time', None)
                age_disp = "N/A"
                created_dt = None
                if created_time:
                    try:
                        created_dt = pd.to_datetime(created_time)
                        if created_dt.tzinfo is None: created_dt = created_dt.tz_localize('UTC')
                        created_dt_local = created_dt.to_pydatetime().astimezone()
                        age_disp = created_dt_local.strftime('%I:%M %p')
                    except: pass

                orders_data.append({
                    'product_id': pid,
                    'side': side,
                    'tp_price': f"${tp_price_dec:,.2f}",
                    'sl_price': f"${sl_price_dec:,.2f}" if sl_price_dec > 0 else "N/A",
                    'current_price': float(current_unit_price),
                    'health': health_score,
                    'mission_value': est_val_str,
                    'upside': upside_str,
                    'age': age_disp,
                    'raw_created_time': created_dt if created_dt else pd.Timestamp.min,
                    'fireballs': fireballs,
                    'shields': shields
                })

        orders_data.sort(key=lambda x: x['raw_created_time'], reverse=True)
        return orders_data
    except Exception as e:
        st.error(f"Error fetching live matches: {e}")
        return []

def get_mission_history(client, limit=10):
    if not client: return []
    try:
        resp = client.list_orders(order_status=["FILLED"], limit=limit*4)
        orders = resp.orders if hasattr(resp, 'orders') else list(resp)
        buy_orders_map = {}
        for o in orders:
            if getattr(o, 'side', '') == 'BUY':
                pid = getattr(o, 'product_id', 'N/A')
                buy_orders_map.setdefault(pid, []).append(o)

        history = []
        for o in orders:
            if len(history) >= limit: break
            if getattr(o, 'side', 'N/A') != 'SELL': continue
            
            oconf = getattr(o, 'order_configuration', None)
            mission_status = "UNKNOWN"
            filled_price = Decimal(getattr(o, 'average_filled_price', '0'))
            
            if oconf:
                if hasattr(oconf, 'limit_limit_gtc') or hasattr(oconf, 'limit_limit_gtd'):
                    mission_status = "SUCCESS"
                elif hasattr(oconf, 'trigger_bracket_gtc'):
                    lim = Decimal(getattr(oconf.trigger_bracket_gtc, 'limit_price', '0'))
                    mission_status = "SUCCESS" if filled_price >= lim else "CRASH LANDED"
                elif hasattr(oconf, 'stop_limit_stop_limit_gtc'):
                    mission_status = "CRASH LANDED"
                elif hasattr(oconf, 'market_market_iot'):
                    mission_status = "ABORTED"
                else:
                    mission_status = "ABORTED"

            pid = getattr(o, 'product_id', 'N/A')
            size = Decimal(getattr(o, 'filled_size', '0'))
            sell_fees = Decimal(getattr(o, 'total_fees', '0'))
            sell_proceeds = (size * filled_price) - sell_fees
            fill_time = getattr(o, 'last_fill_time', None)
            
            profit_str = "N/A"
            net_profit = Decimal('0')
            if pid in buy_orders_map and buy_orders_map[pid]:
                b = buy_orders_map[pid][0]
                b_price = Decimal(getattr(b, 'average_filled_price', '0'))
                b_size = Decimal(getattr(b, 'filled_size', '0'))
                b_fees = Decimal(getattr(b, 'total_fees', '0'))
                cost = (b_size * b_price) + b_fees
                net_profit = sell_proceeds - cost
                profit_str = f"{'+' if net_profit >= 0 else ''}${net_profit:,.2f}"

            time_disp = "N/A"
            raw_time = pd.Timestamp.min
            if fill_time:
                try:
                    dt = pd.to_datetime(fill_time)
                    if dt.tzinfo is None: dt = dt.tz_localize('UTC')
                    dt_local = dt.to_pydatetime().astimezone()
                    raw_time = dt_local
                    time_disp = dt_local.strftime('%Y-%m-%d %I:%M %p')
                except: pass

            history.append({
                'product': pid,
                'proceeds': f"${sell_proceeds:,.2f}",
                'price': f"${filled_price:,.2f}",
                'time': time_disp,
                'raw_time': raw_time,
                'size': f"{size:.4f}",
                'fees': f"${sell_fees:,.2f}",
                'profit': profit_str,
                'raw_profit': net_profit,
                'status': mission_status
            })

        history.sort(key=lambda x: x['raw_time'], reverse=True)
        return history
    except Exception:
        return []

# --- 5. Arcade Demo Simulation Generator ---

def get_demo_orders():
    """Generates rich, live-feeling arcade battles with simulated ticks."""
    btc_delta = (random.random() - 0.45) * 120
    eth_delta = (random.random() - 0.48) * 8
    sol_delta = (random.random() - 0.52) * 1.5
    
    btc_price = 68420.00 + btc_delta
    eth_price = 3520.50 + eth_delta
    sol_price = 148.20 + sol_delta

    return [
        {
            'product_id': 'BTC-USD',
            'side': 'SELL',
            'tp_price': '$70,500.00',
            'sl_price': '$64,000.00',
            'current_price': btc_price,
            'health': 88, # Bull close to K.O. strike!
            'mission_value': '$34,210.00',
            'upside': '+$1,040.00',
            'age': '02:45 PM',
            'fireballs': [
                {'price': '$69,500', 'raw_size': 5.2, 'val_fmt': '$359K', 'pct': 76, 'level': 2},
                {'price': '$70,200', 'raw_size': 12.8, 'val_fmt': '$897K', 'pct': 92, 'level': 3}
            ],
            'shields': [
                {'price': '$67,000', 'raw_size': 8.4, 'val_fmt': '$567K', 'pct': 50, 'level': 2},
                {'price': '$65,000', 'raw_size': 14.1, 'val_fmt': '$930K', 'pct': 18, 'level': 3}
            ]
        },
        {
            'product_id': 'ETH-USD',
            'side': 'SELL',
            'tp_price': '$3,800.00',
            'sl_price': '$3,200.00',
            'current_price': eth_price,
            'health': 53, # Dead-even mid-arena brawl
            'mission_value': '$14,082.00',
            'upside': '+$1,118.00',
            'age': '01:15 PM',
            'fireballs': [
                {'price': '$3,620', 'raw_size': 80.0, 'val_fmt': '$290K', 'pct': 68, 'level': 2},
                {'price': '$3,760', 'raw_size': 250.0, 'val_fmt': '$940K', 'pct': 90, 'level': 3}
            ],
            'shields': [
                {'price': '$3,420', 'raw_size': 95.0, 'val_fmt': '$327K', 'pct': 36, 'level': 2},
                {'price': '$3,280', 'raw_size': 210.0, 'val_fmt': '$697K', 'pct': 12, 'level': 3}
            ]
        },
        {
            'product_id': 'SOL-USD',
            'side': 'SELL',
            'tp_price': '$175.00',
            'sl_price': '$140.00',
            'current_price': sol_price,
            'health': 23, # Bull under pressure near Stop Loss
            'mission_value': '$4,446.00',
            'upside': '+$804.00',
            'age': '11:30 AM',
            'fireballs': [
                {'price': '$158', 'raw_size': 850.0, 'val_fmt': '$131K', 'pct': 50, 'level': 2},
                {'price': '$172', 'raw_size': 2200.0, 'val_fmt': '$374K', 'pct': 88, 'level': 3}
            ],
            'shields': [
                {'price': '$142', 'raw_size': 1800.0, 'val_fmt': '$253K', 'pct': 8, 'level': 3}
            ]
        }
    ]

def get_demo_history():
    return [
        {
            'product': 'BTC-USD',
            'proceeds': '$28,450.00',
            'price': '$69,800.00',
            'time': 'Today 12:40 PM',
            'size': '0.4075',
            'fees': '$17.20',
            'profit': '+$1,650.00',
            'raw_profit': Decimal('1650.00'),
            'status': 'SUCCESS'
        },
        {
            'product': 'AVAX-USD',
            'proceeds': '$5,120.00',
            'price': '$32.10',
            'time': 'Today 09:15 AM',
            'size': '159.50',
            'fees': '$5.10',
            'profit': '-$240.00',
            'raw_profit': Decimal('-240.00'),
            'status': 'CRASH LANDED'
        },
        {
            'product': 'NEAR-USD',
            'proceeds': '$3,890.00',
            'price': '$6.45',
            'time': 'Yesterday 04:22 PM',
            'size': '603.10',
            'fees': '$3.80',
            'profit': '+$430.00',
            'raw_profit': Decimal('430.00'),
            'status': 'SUCCESS'
        }
    ]

# --- 6. Arcade CSS & Theme Engine ---

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Teko:wght@600;700&display=swap');

/* --- Global Arcade Styling --- */
.kombat-banner {
    text-align: center;
    padding: 10px 0 20px 0;
}
.kombat-title {
    font-family: 'Press Start 2P', monospace;
    font-size: 2.2rem;
    color: #ff0055;
    text-shadow: 0 0 10px #ff0055, 0 0 25px #ff5500, 3px 3px 0 #000;
    letter-spacing: 2px;
    margin: 0;
}
.kombat-sub {
    font-family: 'Teko', sans-serif;
    font-size: 1.5rem;
    color: #ffd700;
    text-transform: uppercase;
    letter-spacing: 3px;
    margin-top: 4px;
    text-shadow: 0 0 8px rgba(255, 215, 0, 0.6);
}

/* --- Battle Stage Outer Frame --- */
.arena-card {
    background: radial-gradient(circle at 50% 20%, #151128 0%, #080711 75%, #020205 100%);
    border: 3px solid #ff0055;
    border-radius: 8px;
    box-shadow: 0 0 25px rgba(255, 0, 85, 0.35), inset 0 0 15px rgba(0, 0, 0, 0.8);
    padding: 16px;
    margin-bottom: 30px;
    position: relative;
    overflow: hidden;
}

/* Scanlines overlay */
.arena-card::after {
    content: " ";
    position: absolute;
    top: 0; left: 0; bottom: 0; right: 0;
    background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.35) 50%);
    background-size: 100% 4px;
    pointer-events: none;
    z-index: 20;
    opacity: 0.7;
}

/* --- Top HUD: Redesigned Non-Overlapping Layout --- */
.hud-top-meta {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
    flex-wrap: wrap;
}
.hud-round-badge {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.85rem;
    color: #ffd700;
    text-shadow: 0 0 8px #ffd700, 2px 2px #000;
    background: rgba(255, 215, 0, 0.15);
    border: 1px solid #ffd700;
    padding: 3px 8px;
    border-radius: 4px;
    animation: pulse-vs 2s infinite ease-in-out;
}
.hud-price-pill {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.85rem;
    color: #ffffff;
    background: rgba(0, 0, 0, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.5);
    padding: 3px 10px;
    border-radius: 4px;
    white-space: nowrap;
    box-shadow: 0 0 10px rgba(0, 255, 204, 0.2);
}

.hud-fighters-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}
.fighter-tag-left {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    overflow: hidden;
}
.fighter-tag-right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
    flex: 1;
    overflow: hidden;
}
.tag-name-left {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.72rem;
    color: #00ffcc;
    text-shadow: 0 0 6px #00ffcc;
    white-space: nowrap;
}
.tag-name-right {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.72rem;
    color: #ff3366;
    text-shadow: 0 0 6px #ff3366;
    white-space: nowrap;
    text-align: right;
}
.tag-hp-left {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.7rem;
    color: #00ff66;
    background: rgba(0, 255, 102, 0.15);
    border: 1px solid #00ff66;
    padding: 2px 5px;
    border-radius: 3px;
    white-space: nowrap;
}
.tag-hp-right {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.7rem;
    color: #ff3366;
    background: rgba(255, 51, 102, 0.15);
    border: 1px solid #ff3366;
    padding: 2px 5px;
    border-radius: 3px;
    white-space: nowrap;
}
.hud-vs-text {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.85rem;
    color: #ffd700;
    text-shadow: 0 0 8px #ffd700;
    padding: 0 6px;
    flex-shrink: 0;
}

.hud-lifebars-strip {
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
}
.lifebar-box {
    flex: 1;
    height: 18px;
    background: #111;
    border: 2px solid #fff;
    border-radius: 2px;
    overflow: hidden;
    position: relative;
    box-shadow: 0 0 8px rgba(255,255,255,0.25);
}
.lifebar-fill-bull {
    height: 100%;
    background: linear-gradient(90deg, #ff0055 0%, #ffcc00 35%, #00ff66 100%);
    box-shadow: 0 0 10px #00ff66;
    transition: width 0.8s ease-in-out;
}
.lifebar-fill-bear {
    height: 100%;
    float: right;
    background: linear-gradient(90deg, #ff0055 0%, #ff6600 50%, #ffcc00 100%);
    box-shadow: 0 0 10px #ff0055;
    transition: width 0.8s ease-in-out;
}

@keyframes pulse-vs {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.08); filter: brightness(1.25); }
}

/* --- Climax Banners --- */
.finish-him-banner {
    font-family: 'Press Start 2P', monospace;
    font-size: 1.2rem;
    color: #ff0000;
    text-shadow: 0 0 10px #ff0000, 0 0 25px #ffd700;
    text-align: center;
    margin: 8px 0;
    animation: flash-finish 0.4s infinite alternate;
    letter-spacing: 2px;
}
@keyframes flash-finish {
    0% { opacity: 1; transform: scale(1); }
    100% { opacity: 0.8; transform: scale(1.05); }
}

.danger-banner {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.9rem;
    color: #ffaa00;
    text-shadow: 0 0 8px #ffaa00;
    text-align: center;
    margin: 8px 0;
    animation: pulse-danger 0.8s infinite alternate;
}
@keyframes pulse-danger {
    0% { opacity: 0.5; }
    100% { opacity: 1; }
}

/* --- Battle Stage Arena --- */
.stage-arena {
    height: 280px;
    position: relative;
    background: linear-gradient(to bottom, #110d24 0%, #201338 50%, #150a21 70%, #090312 100%);
    border: 2px solid #33224d;
    border-radius: 4px;
    margin: 12px 0;
    overflow: hidden;
}

/* 3D Perspective Grid Floor */
.stage-floor {
    position: absolute;
    bottom: 0;
    left: -20%;
    width: 140%;
    height: 85px;
    background-image: 
        linear-gradient(rgba(255, 0, 128, 0.4) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 0, 128, 0.4) 1px, transparent 1px);
    background-size: 40px 18px;
    transform: perspective(150px) rotateX(45deg);
    transform-origin: bottom center;
    box-shadow: 0 -10px 25px rgba(255, 0, 128, 0.3);
}

/* Fighters Positioning & Stances */
.fighter-wrapper-bull {
    position: absolute;
    bottom: 40px;
    width: 95px;
    height: 125px;
    z-index: 12;
    transition: left 1.2s cubic-bezier(0.2, 0.8, 0.3, 1);
}
.fighter-wrapper-bear {
    position: absolute;
    bottom: 40px;
    right: 25px;
    width: 105px;
    height: 135px;
    z-index: 11;
}

/* --- High-Energy Arcade Fighting Animations --- */

/* 1. Bull Attack Cycles */
@keyframes bull-combos {
    0%   { transform: translateX(0) translateY(0) rotate(0deg); }
    12%  { transform: translateX(20px) translateY(-4px) rotate(-3deg); } /* Quick jab */
    24%  { transform: translateX(6px) translateY(0) rotate(0deg); }
    38%  { transform: translateX(32px) translateY(-6px) rotate(-6deg); } /* Right cross */
    52%  { transform: translateX(10px) translateY(0) rotate(0deg); }
    68%  { transform: translateX(46px) translateY(-26px) rotate(8deg); } /* Rising Dragon Uppercut! */
    82%  { transform: translateX(22px) translateY(-8px) rotate(3deg); }
    100% { transform: translateX(0) translateY(0) rotate(0deg); }
}

@keyframes bull-hyper-rush {
    0%   { transform: translateX(0) translateY(0) scale(1); filter: drop-shadow(0 0 15px #00ffff); }
    20%  { transform: translateX(36px) translateY(-8px) scale(1.08); filter: drop-shadow(0 0 25px #00ffcc); }
    40%  { transform: translateX(16px) translateY(-2px) scale(1); }
    60%  { transform: translateX(50px) translateY(-24px) rotate(6deg) scale(1.12); filter: drop-shadow(0 0 35px #ffffff); }
    80%  { transform: translateX(26px) translateY(-4px) scale(1.04); }
    100% { transform: translateX(0) translateY(0) scale(1); filter: drop-shadow(0 0 15px #00ffff); }
}

@keyframes bull-defend {
    0%   { transform: translateX(0) rotate(0deg); }
    30%  { transform: translateX(-16px) rotate(5deg); } /* Knocked back */
    50%  { transform: translateX(-12px) rotate(3deg); filter: brightness(1.4) drop-shadow(0 0 14px #ff3300); }
    100% { transform: translateX(0) rotate(0deg); }
}

/* 2. Bear Boss Attack Cycles */
@keyframes bear-attacks {
    0%   { transform: translateX(0) translateY(0) rotate(0deg); }
    18%  { transform: translateX(-26px) translateY(-4px) rotate(-5deg); } /* Heavy claw swipe */
    35%  { transform: translateX(-8px) translateY(0) rotate(0deg); }
    55%  { transform: translateX(-40px) translateY(-12px) rotate(-8deg); } /* Brutal overhead slash */
    70%  { transform: translateX(-16px) translateY(6px) rotate(2deg); } /* Ground smash */
    88%  { transform: translateX(-8px) translateY(0) rotate(0deg); }
    100% { transform: translateX(0) translateY(0) rotate(0deg); }
}

@keyframes bear-dizzy-wobble {
    0%   { transform: rotate(0deg) translateY(0); filter: brightness(0.9); }
    25%  { transform: rotate(-8deg) translateY(5px); }
    50%  { transform: rotate(8deg) translateY(-3px); }
    75%  { transform: rotate(-5deg) translateY(4px); }
    100% { transform: rotate(0deg) translateY(0); filter: brightness(0.9); }
}

@keyframes bear-rampage-rush {
    0%   { transform: translateX(0) scale(1); }
    25%  { transform: translateX(-38px) translateY(-6px) rotate(-8deg) scale(1.08); filter: drop-shadow(0 0 25px #ff0055); }
    50%  { transform: translateX(-16px) translateY(8px) scale(1.04); }
    75%  { transform: translateX(-46px) translateY(-14px) rotate(-10deg) scale(1.12); filter: drop-shadow(0 0 30px #ff0000); }
    100% { transform: translateX(0) scale(1); }
}

/* 3. Limb Specific Animations (Fists, Horns & Claws) */
@keyframes punch-fist-r {
    0%, 100% { transform: translateX(0) scale(1); }
    38%      { transform: translateX(25px) scale(1.4); }
    68%      { transform: translateY(-20px) scale(1.5); }
}
@keyframes punch-fist-l {
    0%, 100% { transform: translateX(0) scale(1); }
    12%      { transform: translateX(20px) scale(1.3); }
    50%      { transform: translateX(26px) scale(1.4); }
}
@keyframes claw-slash-motion {
    0%, 100% { transform: rotate(0deg); }
    20%      { transform: rotate(-25deg) translateY(8px) scale(1.3); }
    60%      { transform: rotate(-35deg) translateY(12px) scale(1.4); }
}
@keyframes headband-flutter {
    0%, 100% { transform: rotate(0deg); }
    50%      { transform: rotate(-15deg) scaleX(1.15); }
}

/* Animation class assignments */
.bull-fighting    { animation: bull-combos 1.8s infinite ease-in-out; }
.bull-finish-him  { animation: bull-hyper-rush 0.75s infinite ease-in-out; }
.bull-staggered   { animation: bull-defend 1.4s infinite ease-in-out; }

.bear-fighting    { animation: bear-attacks 2.0s infinite ease-in-out; }
.bear-dizzy       { animation: bear-dizzy-wobble 1.6s infinite ease-in-out; }
.bear-raging      { animation: bear-rampage-rush 1.4s infinite ease-in-out; }

.bull-fighting .bull-fist-r, .bull-finish-him .bull-fist-r { animation: punch-fist-r 1.8s infinite ease-in-out; }
.bull-fighting .bull-fist-l, .bull-finish-him .bull-fist-l { animation: punch-fist-l 1.8s infinite ease-in-out; }
.bull-headband-flutter { animation: headband-flutter 0.6s infinite alternate ease-in-out; transform-origin: 23px 30px; }
.bear-slash-l { animation: claw-slash-motion 2.0s infinite ease-in-out; transform-origin: 18px 94px; }
.bear-slash-r { animation: claw-slash-motion 2.0s infinite ease-in-out 0.4s; transform-origin: 92px 94px; }

/* 4. Clash Bursts, Slashes & Energy Projectiles */
@keyframes clash-flash {
    0%   { opacity: 0; transform: scale(0.3) rotate(0deg); }
    25%  { opacity: 1; transform: scale(1.4) rotate(15deg); }
    45%  { opacity: 0.9; transform: scale(1.1) rotate(-10deg); }
    70%  { opacity: 0; transform: scale(0.6); }
    100% { opacity: 0; transform: scale(0.3); }
}
.clash-burst {
    position: absolute;
    bottom: 80px;
    z-index: 15;
    font-size: 34px;
    pointer-events: none;
    animation: clash-flash 1.8s infinite ease-in-out;
    filter: drop-shadow(0 0 12px #ffff00) drop-shadow(0 0 20px #ff3300);
}

@keyframes slash-arc {
    0%   { opacity: 0; transform: scale(0.4) rotate(45deg); }
    40%  { opacity: 1; transform: scale(1.3) rotate(-20deg); filter: drop-shadow(0 0 15px #ff0055); }
    65%  { opacity: 0.7; transform: scale(1.0) rotate(-40deg); }
    100% { opacity: 0; transform: scale(0.6); }
}
.slash-arc-fx {
    position: absolute;
    bottom: 75px;
    right: 110px;
    font-size: 38px;
    z-index: 13;
    pointer-events: none;
    animation: slash-arc 2.0s infinite ease-in-out;
}

@keyframes dizzy-spin {
    0%   { transform: rotate(0deg) scale(0.9); }
    50%  { transform: rotate(180deg) scale(1.15); }
    100% { transform: rotate(360deg) scale(0.9); }
}
.dizzy-stars-halo {
    position: absolute;
    top: 15px;
    right: 35px;
    font-size: 24px;
    z-index: 16;
    animation: dizzy-spin 2.2s infinite linear;
    filter: drop-shadow(0 0 10px #ffd700);
}

@keyframes dragon-wave {
    0%   { left: 25%; opacity: 0; transform: scale(0.6); }
    20%  { opacity: 1; transform: scale(1.2); }
    75%  { opacity: 0.9; transform: scale(1.0); }
    100% { left: 80%; opacity: 0; transform: scale(0.5); }
}
.ki-dragon-wave {
    position: absolute;
    bottom: 75px;
    z-index: 14;
    font-size: 32px;
    pointer-events: none;
    animation: dragon-wave 2.8s infinite ease-in-out;
    filter: drop-shadow(0 0 15px #00ffff);
}

/* Glowing Auras */
.aura-strike {
    filter: drop-shadow(0 0 12px #00ffcc) drop-shadow(0 0 25px #00ffff);
}
.aura-danger {
    filter: drop-shadow(0 0 10px #ff3300);
}
.aura-boss {
    filter: drop-shadow(0 0 12px #ff0055) drop-shadow(0 0 20px #990033);
}

/* --- Projectiles (Asks - Bear Hadoukens) --- */
@keyframes fireball-fly {
    0% { transform: translateY(0) scale(0.95); }
    50% { transform: translateY(-6px) scale(1.05); }
    100% { transform: translateY(0) scale(0.95); }
}

.projectile-hadouken {
    position: absolute;
    top: 18px;
    z-index: 14;
    animation: fireball-fly 1.2s infinite ease-in-out;
    cursor: pointer;
    transition: left 0.4s ease;
}
.projectile-hadouken.lvl-1 { font-size: 22px; filter: drop-shadow(0 0 4px #ff5500); }
.projectile-hadouken.lvl-2 { font-size: 32px; filter: drop-shadow(0 0 10px #ff3300); }
.projectile-hadouken.lvl-3 { 
    font-size: 44px; 
    filter: drop-shadow(0 0 16px #ff0000) drop-shadow(0 0 28px #ff6600); 
    animation: fireball-fly 0.8s infinite ease-in-out;
}

/* --- Shields (Bids - Bull Defenses) --- */
@keyframes shield-pulse {
    0% { transform: scale(1); opacity: 0.8; }
    50% { transform: scale(1.15); opacity: 1; filter: drop-shadow(0 0 12px #00ffcc); }
    100% { transform: scale(1); opacity: 0.8; }
}

.support-shield {
    position: absolute;
    bottom: 20px;
    z-index: 10;
    animation: shield-pulse 2s infinite ease-in-out;
    cursor: pointer;
    transition: left 0.4s ease;
}
.support-shield.lvl-1 { font-size: 18px; filter: drop-shadow(0 0 5px #00ccff); }
.support-shield.lvl-2 { font-size: 26px; filter: drop-shadow(0 0 10px #00ffcc); }
.support-shield.lvl-3 { font-size: 38px; filter: drop-shadow(0 0 18px #00ff88); }

.badge-lbl {
    font-family: 'Press Start 2P', monospace;
    font-size: 7px;
    padding: 1px 4px;
    border-radius: 2px;
    white-space: nowrap;
}
.badge-ask { color: #ff9900; background: rgba(0,0,0,0.85); }
.badge-bid { color: #00ffcc; background: rgba(0,0,0,0.85); }

/* --- Telemetry Stats Grid --- */
.telemetry-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-top: 14px;
}
.stat-box {
    background: rgba(12, 8, 26, 0.7);
    border: 1px solid rgba(255, 0, 85, 0.4);
    border-radius: 4px;
    padding: 8px 12px;
    text-align: center;
}
.stat-lbl {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.6rem;
    color: #8899aa;
    margin-bottom: 4px;
    display: block;
    white-space: nowrap;
}
.stat-val {
    font-family: 'Teko', sans-serif;
    font-size: 1.4rem;
    color: #ffffff;
    line-height: 1.2;
    white-space: nowrap;
}

/* --- Mobile Responsiveness --- */
@media (max-width: 650px) {
    .arena-card {
        padding: 10px 8px !important;
    }
    .hud-top-meta {
        gap: 6px !important;
        margin-bottom: 6px !important;
    }
    .hud-round-badge {
        font-size: 0.68rem !important;
        padding: 2px 6px !important;
    }
    .hud-price-pill {
        font-size: 0.68rem !important;
        padding: 2px 8px !important;
    }
    .tag-name-left, .tag-name-right {
        font-size: 0.58rem !important;
    }
    .tag-hp-left, .tag-hp-right {
        font-size: 0.58rem !important;
        padding: 1px 4px !important;
    }
    .hud-vs-text {
        font-size: 0.72rem !important;
        padding: 0 3px !important;
    }
    .lifebar-box {
        height: 14px !important;
    }
    .stage-arena {
        height: 240px !important;
    }
    .telemetry-bar {
        grid-template-columns: repeat(2, 1fr) !important;
        gap: 6px !important;
    }
    .stat-box {
        padding: 6px 8px !important;
    }
    .stat-lbl {
        font-size: 0.5rem !important;
    }
    .stat-val {
        font-size: 1.25rem !important;
    }
    .fighter-wrapper-bull {
        width: 80px !important;
        height: 110px !important;
        bottom: 30px !important;
    }
    .fighter-wrapper-bear {
        width: 88px !important;
        height: 115px !important;
        right: 12px !important;
        bottom: 30px !important;
    }
}


/* --- Kombat Hall of Fame --- */
.hall-card {
    background: #0d0b14;
    border-left: 6px solid #ffd700;
    border-radius: 4px;
    padding: 10px 14px;
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.hall-card.win { border-color: #00ff88; }
.hall-card.loss { border-color: #ff0055; }
.hall-title {
    font-family: 'Press Start 2P', monospace;
    font-size: 0.85rem;
}
</style>
""", unsafe_allow_html=True)

# Header Banner
st.markdown("""
<div class="kombat-banner">
    <h1 class="kombat-title">⚔️ MARKET KOMBAT ⚔️</h1>
    <div class="kombat-sub">BULL [LONG] VS BEAR [BOSS] • ARCADE ORDER BOOK CLASH</div>
</div>
""", unsafe_allow_html=True)

if demo_mode:
    st.info("🕹️ **ARCADE DEMO MODE ACTIVE**: Simulating real-time order clashes and market depth. Toggle off in sidebar for live Coinbase trading.")


def render_clean_html(html_str):
    cleaned = "\n".join([line.strip() for line in html_str.splitlines() if line.strip()])
    st.markdown(cleaned, unsafe_allow_html=True)


# --- 7. SVG Character Fighters & Assets ---

# The Bull Fighter (Martial Arts Bull with Headband & Combat Wraps)
SVG_BULL_RAW = """
<svg viewBox="0 0 100 130" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Glowing Bull Horns -->
  <path d="M22 28 C10 12, 8 0, 3 2 C0 4, 8 20, 24 35 Z" fill="#FFD700" stroke="#FFF" stroke-width="1.5"/>
  <path d="M78 28 C90 12, 92 0, 97 2 C100 4, 92 20, 76 35 Z" fill="#FFD700" stroke="#FFF" stroke-width="1.5"/>
  
  <!-- Bull Head & Snout -->
  <ellipse cx="50" cy="42" rx="28" ry="24" fill="#3D2314" stroke="#1A0D07" stroke-width="2"/>
  <ellipse cx="50" cy="52" rx="17" ry="12" fill="#6E3D1F"/>
  <!-- Nostrils & Golden Septum Ring -->
  <circle cx="43" cy="52" r="3" fill="#1A0D07"/>
  <circle cx="57" cy="52" r="3" fill="#1A0D07"/>
  <path d="M44 55 A6 6 0 0 0 56 55" stroke="#FFD700" stroke-width="3" fill="none"/>
  
  <!-- Red Fighter Headband (Ryu Style) -->
  <rect x="23" y="30" width="54" height="7" fill="#FF0044" rx="2"/>
  <g class="bull-headband-flutter">
    <path d="M23 34 L12 40 L16 33 Z" fill="#FF0044"/>
    <path d="M23 35 L10 46 L15 37 Z" fill="#CC0033"/>
  </g>
  
  <!-- Fierce Eyes -->
  <polygon points="34,35 44,38 37,42" fill="#00FFCC"/>
  <polygon points="66,35 56,38 63,42" fill="#00FFCC"/>
  
  <!-- Muscular Torso -->
  <path d="M30 62 L70 62 L64 100 L36 100 Z" fill="#2E1B10" stroke="#1A0D07" stroke-width="2"/>
  <!-- Combat Wraps / Belt -->
  <rect x="34" y="90" width="32" height="10" fill="#FF0044"/>
  <rect x="38" y="93" width="24" height="4" fill="#FFCC00"/>
  
  <!-- Fists with Glowing Blue Wraps -->
  <circle class="bull-fist-l" cx="22" cy="74" r="10" fill="#00FFCC" stroke="#FFFFFF" stroke-width="2"/>
  <circle class="bull-fist-r" cx="76" cy="70" r="11" fill="#00FFCC" stroke="#FFFFFF" stroke-width="2"/>
  
  <!-- Sturdy Stance Legs -->
  <rect x="34" y="100" width="12" height="24" fill="#1A0D07" rx="3"/>
  <rect x="54" y="100" width="12" height="24" fill="#1A0D07" rx="3"/>
</svg>
"""
SVG_BULL = "".join([l.strip() for l in SVG_BULL_RAW.splitlines()])

# The Bear Boss (Armored Grizzly Boss with Claws & Red Glowing Aura)
SVG_BEAR_RAW = """
<svg viewBox="0 0 110 140" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Bear Ears with Spikes -->
  <circle cx="28" cy="24" r="12" fill="#1C1822" stroke="#FF0055" stroke-width="1.5"/>
  <circle cx="82" cy="24" r="12" fill="#1C1822" stroke="#FF0055" stroke-width="1.5"/>
  <circle cx="28" cy="24" r="6" fill="#FF0055"/>
  <circle cx="82" cy="24" r="6" fill="#FF0055"/>
  
  <!-- Massive Bear Head -->
  <ellipse cx="55" cy="48" rx="36" ry="30" fill="#2A2433" stroke="#100C16" stroke-width="2"/>
  <ellipse cx="55" cy="58" rx="20" ry="15" fill="#423950"/>
  <!-- Snarl Fangs -->
  <path d="M47 62 L49 68 L51 62" fill="#FFFFFF"/>
  <path d="M59 62 L61 68 L63 62" fill="#FFFFFF"/>
  <ellipse cx="55" cy="54" rx="5" ry="3.5" fill="#000"/>
  
  <!-- Glowing Crimson Boss Eyes -->
  <ellipse cx="41" cy="42" rx="5" ry="3" fill="#FF0033"/>
  <ellipse cx="69" cy="42" rx="5" ry="3" fill="#FF0033"/>
  <circle cx="41" cy="42" r="2" fill="#FFF"/>
  <circle cx="69" cy="42" r="2" fill="#FFF"/>
  
  <!-- Heavy Spiked Pauldrons / Armor -->
  <path d="M12 70 L30 55 L38 85 L18 90 Z" fill="#4B1224" stroke="#FF0055" stroke-width="1.5"/>
  <polygon points="12,70 4,62 18,65" fill="#FFCC00"/>
  <path d="M98 70 L80 55 L72 85 L92 90 Z" fill="#4B1224" stroke="#FF0055" stroke-width="1.5"/>
  <polygon points="98,70 106,62 92,65" fill="#FFCC00"/>
  
  <!-- Massive Torso & Scar -->
  <path d="M26 72 L84 72 L76 112 L34 112 Z" fill="#201A27" stroke="#100C16" stroke-width="2"/>
  <path d="M40 78 L65 98" stroke="#FF0033" stroke-width="2" stroke-linecap="round"/>
  
  <!-- Bear Claws (Ready to Slash) -->
  <g class="bear-slash-l">
    <circle cx="18" cy="94" r="11" fill="#100C16" stroke="#FF0055" stroke-width="1.5"/>
    <path d="M10 94 L5 88 M12 99 L7 96 M17 103 L14 102" stroke="#FFD700" stroke-width="2"/>
  </g>
  
  <g class="bear-slash-r">
    <circle cx="92" cy="94" r="11" fill="#100C16" stroke="#FF0055" stroke-width="1.5"/>
    <path d="M100 94 L105 88 M98 99 L103 96 M93 103 L96 102" stroke="#FFD700" stroke-width="2"/>
  </g>
  
  <!-- Legs -->
  <rect x="32" y="112" width="16" height="24" fill="#140F1B" rx="3"/>
  <rect x="62" y="112" width="16" height="24" fill="#140F1B" rx="3"/>
</svg>
"""
SVG_BEAR = "".join([l.strip() for l in SVG_BEAR_RAW.splitlines()])

# --- 8. Data Fetching & Execution ---

if demo_mode:
    orders = get_demo_orders()
    history = get_demo_history()
else:
    client = get_api_client()
    if client:
        with st.spinner("⚔️ Scanning Coinbase Arena for active orders..."):
            orders = get_open_orders_data(client)
            history = get_mission_history(client, limit=10)
    else:
        orders = []
        history = []

# --- 9. Arena Render Loop ---

if not orders:
    empty_html = """<div class="arena-card" style="text-align: center; padding: 40px;">
<h2 style="font-family: 'Press Start 2P'; color: #ffd700;">NO FIGHTERS IN THE ARENA</h2>
<p style="font-family: 'Teko'; font-size: 1.4rem; color: #8899aa;">
No active open limit or bracket orders found on your Coinbase account.
</p>
<p style="color: #ff0055;">Toggle <b>🕹️ Arcade Demo Mode</b> in the sidebar to preview the battle engine!</p>
</div>"""
    st.markdown(empty_html, unsafe_allow_html=True)
else:
    for idx, o in enumerate(orders):
        pid = o['product_id']
        health = int(o.get('health', 50))
        price_disp = f"${o['current_price']:,.2f}"
        tp_disp = o.get('tp_price', 'N/A')
        sl_disp = o.get('sl_price', 'N/A')
        val_disp = o.get('mission_value', 'N/A')
        upside_disp = o.get('upside', 'N/A')
        age_disp = o.get('age', 'N/A')
        side = o.get('side', 'BUY')
        
        bull_hp = max(0, min(100, health))
        bear_hp = max(0, min(100, 100 - health))
        bull_left_pct = int(10 + (bull_hp * 0.55))
        
        is_finish_him = bull_hp >= 85
        is_staggered = bull_hp <= 20
        aura_class = "aura-strike" if bull_hp > 50 else ("aura-danger" if is_staggered else "")
        
        fireball_html = ""
        for fb in o.get('fireballs', []):
            lvl = fb.get('level', 2)
            pos = fb.get('pct', 50)
            icon = "☄️" if lvl == 1 else ("🔥" if lvl == 2 else "💥")
            fb_price = fb['price']
            fb_val = fb['val_fmt']
            fireball_html += f'<div class="projectile-hadouken lvl-{lvl}" style="left: {pos}%;" title="Sell Wall: {fb_price} (Vol: {fb_val})">{icon}<div class="badge-lbl badge-ask">{fb_price}</div></div>'

        shield_html = ""
        for sh in o.get('shields', []):
            lvl = sh.get('level', 2)
            pos = sh.get('pct', 30)
            icon = "✨" if lvl == 1 else ("🛡️" if lvl == 2 else "⚡")
            sh_price = sh['price']
            sh_val = sh['val_fmt']
            shield_html += f'<div class="support-shield lvl-{lvl}" style="left: {pos}%;" title="Buy Support: {sh_price} (Vol: {sh_val})">{icon}<div class="badge-lbl badge-bid">{sh_price}</div></div>'

        alert_banner = ""
        if is_finish_him:
            alert_banner = '<div class="finish-him-banner">⚡ FINISH HIM! STRIKE TAKE PROFIT! ⚡</div>'
            bull_anim = "bull-finish-him"
            bear_anim = "bear-dizzy"
            extra_vfx = '<div class="dizzy-stars-halo">💫 ⭐ 💫</div><div class="ki-dragon-wave">⚡🐉</div>'
        elif is_staggered:
            alert_banner = '<div class="danger-banner">⚠️ DANGER: BULL STAGGERED NEAR STOP LOSS ⚠️</div>'
            bull_anim = "bull-staggered"
            bear_anim = "bear-raging"
            extra_vfx = '<div class="slash-arc-fx">🩸</div>'
        else:
            bull_anim = "bull-fighting"
            bear_anim = "bear-fighting"
            extra_vfx = '<div class="slash-arc-fx">⚔️</div>'

        clash_pos = min(76, bull_left_pct + 15)
        clash_vfx = f'<div class="clash-burst" style="left: {clash_pos}%;">💥</div>'

        yield_color = '#00ff66' if '+' in upside_disp else '#ff3366'

        bout_html = f"""<div class="arena-card">
<div class="hud-top-meta">
<span class="hud-round-badge">ROUND {idx + 1}</span>
<span class="hud-price-pill">{pid} • {price_disp}</span>
</div>
<div class="hud-fighters-row">
<div class="fighter-tag-left">
<span class="tag-name-left">THE BULL</span>
<span class="tag-hp-left">{bull_hp}% HP</span>
</div>
<div class="hud-vs-text">VS</div>
<div class="fighter-tag-right">
<span class="tag-hp-right">{bear_hp}% HP</span>
<span class="tag-name-right">BEAR BOSS [TP {tp_disp}]</span>
</div>
</div>
<div class="hud-lifebars-strip">
<div class="lifebar-box">
<div class="lifebar-fill-bull" style="width: {bull_hp}%;"></div>
</div>
<div class="lifebar-box">
<div class="lifebar-fill-bear" style="width: {bear_hp}%;"></div>
</div>
</div>
{alert_banner}
<div class="stage-arena">
<div class="stage-floor"></div>
{fireball_html}
{shield_html}
{clash_vfx}
{extra_vfx}
<div class="fighter-wrapper-bull {bull_anim} {aura_class}" style="left: {bull_left_pct}%;">
{SVG_BULL}
</div>
<div class="fighter-wrapper-bear {bear_anim} aura-boss">
{SVG_BEAR}
</div>
</div>
<div class="telemetry-bar">
<div class="stat-box">
<span class="stat-lbl">MATCH CLOCK</span>
<span class="stat-val" style="color: #00ffcc;">{age_disp}</span>
</div>
<div class="stat-box">
<span class="stat-lbl">MARKET STRIKE</span>
<span class="stat-val" style="color: #ffd700;">{price_disp}</span>
</div>
<div class="stat-box">
<span class="stat-lbl">BOUNTY PURSE</span>
<span class="stat-val" style="color: #ffffff;">{val_disp}</span>
</div>
<div class="stat-box">
<span class="stat-lbl">EST. YIELD</span>
<span class="stat-val" style="color: {yield_color};">{upside_disp}</span>
</div>
</div>
</div>"""
        st.markdown(bout_html, unsafe_allow_html=True)

# --- 10. Kombat Hall of Fame (Match History) ---

if history:
    st.markdown("### 🏆 KOMBAT HALL OF FAME (RECENT BOUTS)")
    for h in history:
        status = h.get('status', 'SUCCESS')
        is_win = (status == 'SUCCESS')
        card_class = "win" if is_win else "loss"
        badge_text = "K.O. - VICTORY" if is_win else ("FATALITY - DEFEAT" if status == 'CRASH LANDED' else "MATCH ABORTED")
        badge_color = "#00ff88" if is_win else "#ff0055"
        
        hist_html = f"""<div class="hall-card {card_class}">
<div>
<span class="hall-title" style="color: {badge_color};">{badge_text}: {h['product']}</span>
<span style="font-size: 0.85rem; color: #8899aa; margin-left: 12px;">{h['time']}</span>
</div>
<div style="font-family: 'Teko'; font-size: 1.3rem;">
<span style="color: #ffffff; margin-right: 15px;">PRICE: {h['price']}</span>
<span style="color: {badge_color}; font-weight: bold;">PROFIT: {h['profit']}</span>
</div>
</div>"""
        st.markdown(hist_html, unsafe_allow_html=True)

# --- 11. Auto-Refresh Logic ---

if auto_refresh:
    time.sleep(30)
    st.rerun()
