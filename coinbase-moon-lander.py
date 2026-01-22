
import streamlit as st
import pandas as pd
import time
import os
import logging
from decimal import Decimal
from datetime import datetime
from dotenv import load_dotenv
import textwrap

# --- 1. Configuration & Setup ---

st.set_page_config(page_title="Coinbase Moon Lander", page_icon="🚀", layout="wide")

# Configure Logging
logging.basicConfig(level=logging.CRITICAL)
# Suppress Coinbase logs if library is present
try:
    logging.getLogger('coinbase.RESTClient').setLevel(logging.CRITICAL)
except:
    pass

# Try to import Coinbase SDK
try:
    from coinbase.rest import RESTClient
except ImportError:
    st.error("🔴 **Dependency Missing**: This app requires the `coinbase-advanced-py` library.")
    st.code("pip install coinbase-advanced-py", language="bash")
    st.stop()

# --- 2. Auth Logic (Shareable) ---

def get_api_client():
    """
    Attempts to load credentials from:
    1. Environment Variables/ .env file
    2. Streamlit Sidebar Inputs
    """
    # 1. Try .env in current or parent dirs
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Try finding .env in up to 2 parent levels
    for path in [os.path.join(script_dir, '.env'), 
                 os.path.join(script_dir, '../.env'), 
                 os.path.join(script_dir, '../../.env')]:
        if os.path.exists(path):
            load_dotenv(dotenv_path=path)
            break
            
    api_key = os.getenv('CB_API_KEY')
    api_secret = os.getenv('CB_API_SECRET')

    # 1.5. Try st.secrets (Streamlit Cloud)
    if not api_key or not api_secret:
        try:
            # Check if secrets are available (they might be under a 'coinbase' section or top level)
            # User said "set my api keys in the safe area", usually maps to top level or custom section.
            # We'll assume top level names as per standard or 'CB_API_KEY' keys.
            if "CB_API_KEY" in st.secrets:
                api_key = st.secrets["CB_API_KEY"]
            if "CB_API_SECRET" in st.secrets:
                api_secret = st.secrets["CB_API_SECRET"]
        except FileNotFoundError:
            pass # No secrets file found
        except Exception:
            pass
    
    # 2. Main Input fallback (No Sidebar)
    if not api_key or not api_secret:
        # Check Session State
        if 'api_key' in st.session_state:
            api_key = st.session_state.api_key
            api_secret = st.session_state.api_secret
        
        if not api_key:
            st.header("🔑 API Credentials")
            st.info("Environment variables not found. Please enter your Coinbase Advanced Trade API keys to continue.")
            
            c1, c2 = st.columns(2)
            with c1:
                k = st.text_input("API Key", type="password")
            with c2:
                s = st.text_input("API Secret", type="password")
                
            if k and s:
                st.session_state.api_key = k
                st.session_state.api_secret = s
                st.rerun()
        
            st.warning("⚠️ Waiting for API Keys...")
            st.stop()
            return None

    return RESTClient(api_key=api_key, api_secret=api_secret)



# --- 4. Backend Logic (Inlined from account_manager.py) ---

def get_best_bid(client, product_id):
    """Fetches the best bid for a product."""
    if not client: return None
    try:
        ticker = client.get_product_book(product_id=product_id, limit=1)
        if ticker and hasattr(ticker, 'pricebook') and hasattr(ticker.pricebook, 'bids') and len(ticker.pricebook.bids) > 0:
             return Decimal(str(ticker.pricebook.bids[0].price))
    except Exception:
        pass
    return None

def get_asset_price(client, asset):
    """Gets current price for an asset (USD/USDC)."""
    if asset in ['USD', 'USDC']: return Decimal('1.0')
    
    price = get_best_bid(client, f"{asset}-USD")
    if price is None:
        price = get_best_bid(client, f"{asset}-USDC")
    return price

def get_open_orders_data(client):
    """
    Scans for open orders and returns 'Moon Mission' compatible data.
    Only focuses on orders that have potential for plotting (Limit/Bracket).
    """
    if not client: return []
    
    try:
        orders_gen = client.list_orders(order_status=["OPEN"]) 
        orders = []
        if hasattr(orders_gen, 'orders'):
             orders = orders_gen.orders
        else:
             orders = list(orders_gen)

        if not orders: return []

        orders_data = []

        for o in orders:
            pid = getattr(o, 'product_id', 'N/A')
            side = getattr(o, 'side', 'N/A')
            oconf = getattr(o, 'order_configuration', None)
            
            # Extract TP/SL/Entry
            tp_price_dec = Decimal('0')
            sl_price_dec = Decimal('0')
            size_dec = Decimal('0')
            current_unit_price = get_asset_price(client, pid.split('-')[0]) or Decimal('0')
            
            # Parse Config
            if oconf:
                if hasattr(oconf, 'limit_limit_gtc'):
                    c = oconf.limit_limit_gtc
                    tp_price_dec = Decimal(getattr(c, 'limit_price', '0'))
                    size_dec = Decimal(getattr(c, 'base_size', '0'))
                    # For standard Limit orders, we treat them as TP missions.
                    # We need a baseline "start" to visualize progress. 
                    # We use the current price as the "floor" (SL) so it shows relative distance.
                    sl_price_dec = get_asset_price(client, pid.split('-')[0]) or Decimal('0') 
                elif hasattr(oconf, 'trigger_bracket_gtc'):
                     c = oconf.trigger_bracket_gtc
                     limit_price = getattr(c, 'limit_price', None)
                     stop_price = getattr(c, 'stop_trigger_price', None)
                     size_dec = Decimal(getattr(c, 'base_size', '0'))
                     if limit_price: tp_price_dec = Decimal(limit_price)
                     if stop_price: sl_price_dec = Decimal(stop_price)
                elif hasattr(oconf, 'stop_limit_stop_limit_gtc'):
                     # PENDING / STOP LIMIT ORDER
                     c = oconf.stop_limit_stop_limit_gtc
                     stop_price = getattr(c, 'stop_price', None)
                     limit_price = getattr(c, 'limit_price', None)
                     size_dec = Decimal(getattr(c, 'base_size', '0'))
                     if stop_price: sl_price_dec = Decimal(stop_price)
                     # For a stop limit, the limit price is usually the execution price.
                     # If it's a BUY stop limit, we want price to go UP to it? 
                     # Or if it's a STOP LOSS style, we want to stay ABOVE it.
                     # Let's assume it's a standard stop loss or breakout.
                     pass

            # Calculate Health Score (The "Fuel")
            # Health = 0 (Hit SL) -> 100 (Hit TP)
            health_score = 50 # Default middle
            
            # Logic: If we rely on Bracket, we have TP and SL.
            if tp_price_dec > 0 and sl_price_dec > 0 and current_unit_price > 0:
                try:
                    total_range = tp_price_dec - sl_price_dec
                    if total_range != 0:
                        progress = current_unit_price - sl_price_dec
                        pct = (progress / total_range) * 100
                        health_score = max(0, min(100, int(pct)))
                except: pass
            elif tp_price_dec > 0 and current_unit_price > 0:
                 # Only TP (Limit Sell), assume we want it to go UP to TP.
                 # Let's arbitrary set 0% as 80% of current price?
                 # Better: show as just "In Flight"
                     pass
            elif sl_price_dec > 0 and current_unit_price > 0:
                 # STOP LIMIT without TP (Pure protection or entry)
                 # We can visualize this!
                 # If side is SELL (Stop Loss), we want to stay ABOVE SL.
                 # If side is BUY (Breakout), we want to go UP to SL (Trigger).
                 
                 diff = current_unit_price - sl_price_dec
                 # Arbitrary range for visualization: 10% movement
                 range_buffer = sl_price_dec * Decimal('0.1') 
                 
                 if side == 'SELL':
                      # STOP LOSS: 0% is at SL. 100% is securely above (SL + 10%)
                      # Actually, let's reverse semantics for "Health". 
                      # If logic is "Health = Distance from Danger", then:
                      # Danger = SL. Safe = Current.
                      if current_unit_price <= sl_price_dec: health_score = 0
                      else:
                          dist = current_unit_price - sl_price_dec
                          pct = (dist / range_buffer) * 50 # Scale up to 50% "safe" zone
                          health_score = 50 + min(50, int(pct))
                 else:
                      # BUY STOP (Breakout): Target IS the SL price (Trigger).
                      # So we WANT to go there.
                      # 0% = Current - 10%. 100% = SL.
                      if current_unit_price >= sl_price_dec: health_score = 100
                      else:
                           dist_to_go = sl_price_dec - current_unit_price
                           # progress
                           pct = (1 - (dist_to_go / range_buffer)) * 100
                           health_score = max(0, min(99, int(pct)))

            # Only add if we have some data
            if tp_price_dec > 0 or sl_price_dec > 0:

                # Calculate Estimated Mission Value & Upside
                # "Payload Value" = Current Market Value of the position
                # "Est. Yield" = Potential Profit (Target - Current)
                est_value_str = "N/A"
                upside_str = "N/A"
                
                if size_dec > 0 and current_unit_price > 0:
                     # Payload = Curent Value
                     current_val = size_dec * current_unit_price
                     est_value_str = f"${current_val:,.2f}"
                     
                     if tp_price_dec > 0:
                         target_val = size_dec * tp_price_dec
                         upside = target_val - current_val
                         # Only show positive upside (if retrearing, it's technically negative upside/drawdown from target)
                         symbol = "+" if upside >= 0 else ""
                         upside_str = f"{symbol}${upside:,.2f}"
                         
                elif current_unit_price > 0 and size_dec > 0:
                     # Fallback to current value if no TP
                     est_value = size_dec * current_unit_price
                     est_value_str = f"~${est_value:,.2f}"

            # Extract Created Time & Calculate Age
            created_time = getattr(o, 'created_time', None)
            age_disp = "N/A"
            created_dt = None # Reset for each iteration
            
            if created_time:
                try:
                    # Handle Coinbase timestamp format (ISO 8601) - usually UTC
                    created_dt = pd.to_datetime(created_time)
                    
                    # Ensure properly localized to UTC first
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.tz_localize('UTC')
                    
                    # Convert to Local System Time for display
                    # Use Python's standard datetime for robust astimezone conversion
                    created_dt_local = created_dt.to_pydatetime().astimezone()
                    now_dt_local = datetime.now().astimezone()

                    # If same day, show only time. Else show Date + Time
                    if created_dt_local.date() == now_dt_local.date():
                         age_disp = created_dt_local.strftime('%I:%M %p')
                    else:
                         age_disp = created_dt_local.strftime('%Y-%m-%d %I:%M %p')
                         
                except Exception as e:
                    # logging.error(f"Time conversion error: {e}")
                    pass

            orders_data.append({
                'product_id': pid,
                'side': side,
                'tp_price': f"${tp_price_dec}",
                'sl_price': f"${sl_price_dec}" if sl_price_dec > 0 else "N/A",
                'current_price': float(current_unit_price),
                'health': health_score,
                'mission_value': est_value_str,
                'upside': upside_str,
                'age': age_disp,
                'raw_created_time': created_dt if created_dt else pd.Timestamp.min.replace(tzinfo=None)
            })

        # Sort by raw_created_time descending (newest first)
        orders_data.sort(key=lambda x: x['raw_created_time'], reverse=True)

        return orders_data

    except Exception as e:
        st.error(f"Error fetching missions: {e}")
        return []

def get_mission_history(client, limit=10):
    """
    Fetches recently filled SELL orders to visualize as 'Landed Missions'.
    INCLUDES: Success (Limit Sells), Crash Landings (Stop Loss), and Aborted (Market Sells).
    """
    if not client: return []
    
    try:
        # Fetch filled orders. 
        # Increase limit to look back deeper for matching BUYs
        resp = client.list_orders(order_status=["FILLED"], limit=limit*5)
        orders = []
        if hasattr(resp, 'orders'):
             orders = resp.orders
        else:
             orders = list(resp)
             
        # Index BUY orders by Product ID for matching
        # Key: ProductID, Value: List of orders (sorted newest to oldest by default)
        buy_orders_map = {}
        for o in orders:
             if getattr(o, 'side', '') == 'BUY':
                 pid = getattr(o, 'product_id', 'N/A')
                 if pid not in buy_orders_map: buy_orders_map[pid] = []
                 buy_orders_map[pid].append(o)

        history = []
        for o in orders:
            # We collect enough candidates to hopefully get 'limit' number of VALID missions
            # But since we now accept ALL sells, this buffer is less critical but good to have.
            if len(history) >= limit: break
            
            side = getattr(o, 'side', 'N/A')
            if side != 'SELL': continue
            
            # --- DETERMINE STATUS ---
            oconf = getattr(o, 'order_configuration', None)
            mission_status = "UNKNOWN"
            
            avg_price_str = getattr(o, 'average_filled_price', '0')
            filled_price = Decimal(avg_price_str)
            
            if oconf:
                if hasattr(oconf, 'limit_limit_gtc') or hasattr(oconf, 'limit_limit_gtd'):
                     # Standard Limit Sell -> Assumed Success/Take Profit
                     mission_status = "SUCCESS"
                elif hasattr(oconf, 'trigger_bracket_gtc'):
                     c = oconf.trigger_bracket_gtc
                     limit_price = Decimal(getattr(c, 'limit_price', '0'))
                     # If we sold at or above limit price -> Success
                     if filled_price >= limit_price:
                         mission_status = "SUCCESS"
                     else:
                         # Sold below limit (Stop Price triggered) -> Crash
                         mission_status = "CRASH LANDED"
                elif hasattr(oconf, 'stop_limit_stop_limit_gtc') or hasattr(oconf, 'stop_limit_stop_limit_gtd'):
                     # Stop Limit Sell -> Usually a Stop Loss -> Crash
                     mission_status = "CRASH LANDED"
                elif hasattr(oconf, 'market_market_iot'):
                     # Market Sell -> Manual Eject -> Aborted
                     mission_status = "ABORTED"
                else:
                     # Fallback
                     mission_status = "ABORTED"
            
            # Identify Product & Metrics
            pid = getattr(o, 'product_id', 'N/A')
            size_str = getattr(o, 'filled_size', '0')
            fill_time = getattr(o, 'last_fill_time', None)
            
            size = Decimal(size_str)
            sell_price = Decimal(avg_price_str)
            sell_total_val = size * sell_price
            sell_fees = Decimal(getattr(o, 'total_fees', '0'))
            sell_proceeds = sell_total_val - sell_fees
            
            # --- PROFIT CALCULATION ---
            # Attempt to find a matching BUY order
            cost_basis = Decimal('0')
            net_profit = Decimal('0')
            profit_str = "N/A"
            
            if pid in buy_orders_map:
                potential_buys = buy_orders_map[pid]
                matched_buy = None
                
                # Filter for Buys OLDER than this Sell
                sell_time = pd.to_datetime(fill_time) if fill_time else datetime.now()
                if sell_time.tzinfo is None: sell_time = sell_time.tz_localize('UTC')

                for b in potential_buys:
                    b_time_str = getattr(b, 'last_fill_time', None)
                    if not b_time_str: continue
                    b_time = pd.to_datetime(b_time_str)
                    if b_time.tzinfo is None: b_time = b_time.tz_localize('UTC')
                    
                    if b_time < sell_time:
                         # Found a buy that happened before this sell.
                         # Check size match?
                         b_size = Decimal(getattr(b, 'filled_size', '0'))
                         diff = abs(b_size - size)
                         # Tolerance: 1%
                         if diff < (size * Decimal('0.01')):
                             matched_buy = b
                             break
                
                # If no exact size match, fallback to most recent previous buy
                if not matched_buy:
                     for b in potential_buys:
                         b_time_str = getattr(b, 'last_fill_time', None)
                         if not b_time_str: continue
                         b_time = pd.to_datetime(b_time_str)
                         if b_time.tzinfo is None: b_time = b_time.tz_localize('UTC')
                         
                         if b_time < sell_time:
                             matched_buy = b
                             break
            
                if matched_buy:
                    buy_price = Decimal(getattr(matched_buy, 'average_filled_price', '0'))
                    buy_size = Decimal(getattr(matched_buy, 'filled_size', '0'))
                    buy_fees = Decimal(getattr(matched_buy, 'total_fees', '0'))
                    
                    # Cost = Amount Spent to get these coins (approximate if size mismatch)
                    # We treat the BUY order as the cost basis source. 
                    # If sizes differ drastically, this might be off, but usually 1:1 in this bot.
                    cost_basis = (buy_size * buy_price) + buy_fees
                    
                    # Net Profit = Proceeds - Cost
                    net_profit = sell_proceeds - cost_basis
                    
                    symbol = "+" if net_profit >= 0 else ""
                    profit_str = f"{symbol}${net_profit:,.2f}"

            
            time_disp = "N/A"
            created_dt_local = pd.Timestamp.min.replace(tzinfo=None) # default for sorting

            if fill_time:
                try:
                    dt = pd.to_datetime(fill_time)
                    if dt.tzinfo is None: dt = dt.tz_localize('UTC')
                    dt_local = dt.to_pydatetime().astimezone()
                    created_dt_local = dt_local # For sorting
                    time_disp = dt_local.strftime('%Y-%m-%d %I:%M %p')
                except: pass
                
            history.append({
                'id': getattr(o, 'order_id', ''),
                'product': pid,
                'proceeds': f"${sell_proceeds:,.2f}", 
                'price': f"${sell_price:,.2f}",
                'time': time_disp,
                'raw_time': created_dt_local, # For sorting
                'size': f"{size:.4f}",
                'fees': f"${sell_fees:,.2f}",
                'profit': profit_str,
                'raw_profit': net_profit if profit_str != "N/A" else Decimal('-999999'),
                'status': mission_status
            })
            
        # Ensure sorted by time (Newest First) just in case
        history.sort(key=lambda x: x['raw_time'], reverse=True)
            
        return history
        
    except Exception as e:
        # logging.error(f"History fetch error: {e}")
        return []

# --- 5. Main UI & Visualization ---

st.title("Coinbase Moon Lander")
st.markdown("*Visualizing your trade trajectories in real-time.*")

# Custom CSS for Space Theme & HUD
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');

/* --- HUD Animations --- */
@keyframes scanline {
    0% { transform: translateY(-100%); }
    100% { transform: translateY(100%); }
}
@keyframes flicker {
    0% { opacity: 0.97; }
    5% { opacity: 0.95; }
    10% { opacity: 0.9; }
    15% { opacity: 0.95; }
    20% { opacity: 0.99; }
    50% { opacity: 0.95; }
    80% { opacity: 0.9; }
    100% { opacity: 0.97; }
}
@keyframes pulse-glow {
    0% { box-shadow: 0 0 5px rgba(0, 243, 255, 0.2), inset 0 0 5px rgba(0, 243, 255, 0.1); }
    50% { box-shadow: 0 0 20px rgba(0, 243, 255, 0.6), inset 0 0 10px rgba(0, 243, 255, 0.3); }
    100% { box-shadow: 0 0 5px rgba(0, 243, 255, 0.2), inset 0 0 5px rgba(0, 243, 255, 0.1); }
}
@keyframes engine-thrust {
    0% { height: 15px; opacity: 0.8; }
    100% { height: 25px; opacity: 1; }
}
@keyframes star-fly {
    from { transform: translateX(0); }
    to { transform: translateX(-2000px); }
}

/* --- Optimized Rendering Hints --- */
.flight-deck {
    contain: layout paint style;
}
.starfield {
    will-change: transform;
    /* Force GPU layer creation */
    transform: translateZ(0); 
}
.ship-container {
    will-change: left, transform; /* 'left' changes during transition, transform for rotation */
}

/* --- Rocket Engine Plume --- */
/* --- Rocket Engine Plume --- */
@keyframes engine-flicker {
    0% { transform: translateY(-50%) scale(1, 0.8); opacity: 0.9; }
    100% { transform: translateY(-50%) scale(1.2, 1.1); opacity: 1; }
}

.engine-plume {
    position: absolute;
    top: 50%;
    left: -24px; /* Shifted slightly more left to accommodate longer flame */
    width: 50px; /* Slightly longer */
    height: 14px;
    /* Flame Gradient: Transparent -> Orange -> Yellow -> White Core (at engine) */
    background: linear-gradient(to right, transparent, rgba(255, 69, 0, 0.9), rgba(255, 215, 0, 1), #ffffff);
    border-radius: 50% 0 0 50%;
    transform: translateY(-50%);
    /* PERFORMANCE: Removed blur and complex shadow to save CPU */
    will-change: transform, opacity;
    z-index: -1;
    animation: engine-flicker 0.08s infinite alternate;
    /* Simple faint glow only */
    box-shadow: 0 0 5px rgba(255, 100, 0, 0.5);
}

/* Plume for Retreating (Flying Left) */
.ship-container.retreat .engine-plume {
    left: auto;
    right: -24px;
    /* Reverse Gradient: White -> Yellow -> Orange -> Transparent */
    background: linear-gradient(to left, transparent, rgba(255, 69, 0, 0.9), rgba(255, 215, 0, 1), #ffffff);
    border-radius: 0 50% 50% 0;
}

/* --- Containers --- */
.hud-container {
    background-color: #050a10;
    color: #aaccff;
    font-family: 'Share Tech Mono', monospace;
    border: 1px solid #1e3a5a;
    border-radius: 4px;
    padding: 15px;
    margin-bottom: 25px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 0 15px rgba(0,0,0,0.5);
}
.hud-container::before {
    content: " ";
    display: block;
    position: absolute;
    top: 0; left: 0; bottom: 0; right: 0;
    background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06));
    z-index: 2;
    background-size: 100% 2px, 3px 100%;
    pointer-events: none;
}

/* --- Header --- */
.mission-h.telemetry-grid {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    margin-top: 15px;
    border-top: 1px dotted #1e3a5a;
    padding-top: 15px;
    overflow-x: auto;
}
.t-module {
    background: rgba(30, 58, 90, 0.4);
    border: 1px solid rgba(30, 58, 90, 0.5);
    padding: 8px;
    border-radius: 2px;
    min-width: 100px; /* Prevent crushing */
    flex: 1;
    display: flex;
    flex-direction: column;
}
.t-label {
    display: block;
    font-size: 0.75em; /* Slightly larger */
    color: #88aacc; /* Brighter blue for contrast */
    margin-bottom: 2px;
    white-space: nowrap;
}
.mission-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #1e3a5a;
    padding-bottom: 8px;
    margin-bottom: 15px;
}
.mission-title {
    font-size: 1.5em;
    color: #4facfe;
    text-transform: uppercase;
    text-shadow: 0 0 5px #4facfe;
    letter-spacing: 2px;
}
.mission-status {
    font-size: 0.9em;
    padding: 2px 8px;
    border: 1px solid;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* --- Track (Space) --- */
.flight-deck {
    position: relative;
    height: 160px; /* Increased height to prevent clipping */
    background: #000;
    border: 1px solid #333;
    margin: 15px 0;
    overflow: hidden;
    perspective: 1000px;
}
.starfield {
    position: absolute;
    width: 200%;
    height: 100%;
    background-image: 
        radial-gradient(1px 1px at 10px 10px, white, transparent),
        radial-gradient(1px 1px at 123px 45px, white, transparent),
        radial-gradient(2px 2px at 50px 80px, #88ccff, transparent),
        radial-gradient(1.5px 1.5px at 200px 20px, white, transparent);
    background-size: 300px 200px;
    animation: star-fly 30s linear infinite;
    opacity: 0.6;
}

.ship-container {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 60px; 
    height: 100px;
    z-index: 10;
    transition: left 1.5s cubic-bezier(0.22, 1, 0.36, 1);
}

/* SVG Ship Styling */
.ship-svg {
    width: 100%;
    height: 100%;
    filter: drop-shadow(0 0 8px rgba(0, 243, 255, 0.6));
    transform: rotate(90deg); /* Face right by default */
}
.ship-container.retreat .ship-svg {
    transform: rotate(-90deg); /* Face left */
    filter: drop-shadow(0 0 8px rgba(255, 75, 75, 0.6));
}
.ship-container.staging .ship-svg {
    transform: rotate(0deg); /* Disable rotation for Staging (it's drawn right-oriented) */
    filter: drop-shadow(0 0 5px rgba(255, 170, 0, 0.4));
}
/* Staging specific plume (venting smoke at base) */
.ship-container.staging .engine-plume {
    display: none; /* Hide standard engine plume */
}
/* Staging specific price tag positioning to avoid overlap */
.ship-container.staging .price-tag {
    top: -30px; 
}
""", unsafe_allow_html=True)

# Main Execution Logic
client = get_api_client()
if client:
    with st.spinner("🔭 Scanning Deep Space for missions..."):
            orders = get_open_orders_data(client)
else:
    orders = []

if not orders:
    st.info("No active moon missions initiated.")
else:
    st.markdown(f"### Active Trajectories: {len(orders)}")
    
    # SVG Ship Assets
    # Normal Flight: Detailed Gold Rocket (No Launchpad)
    svg_ship_normal = textwrap.dedent("""
    <svg viewBox="0 0 60 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <!-- Rocket Body (Vertical) -->
    <path d="M30 20 L38 35 V85 H22 V35 L30 20 Z" fill="#E0E0E0" stroke="#FFF" stroke-width="2"/>
    <!-- Nose Cone -->
    <path d="M30 20 L38 35 H22 L30 20 Z" fill="#FFD700" stroke="#FFD700" stroke-width="1"/>
    <!-- Fins -->
    <path d="M22 75 L14 88 H22 V75 Z" fill="#FF4500" stroke="#FFF" stroke-width="1"/>
    <path d="M38 75 L46 88 H38 V75 Z" fill="#FF4500" stroke="#FFF" stroke-width="1"/>
    <!-- Engine Nozzle -->
    <path d="M26 85 L24 92 H36 L34 85" fill="#333"/>
    </svg>
    """)
    
    # Alert Flight: Detailed Rocket (Red Warning Scheme)
    svg_ship_alert = textwrap.dedent("""
    <svg viewBox="0 0 60 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <!-- Rocket Body (Vertical) - Red Warning -->
    <path d="M30 20 L38 35 V85 H22 V35 L30 20 Z" fill="#8B0000" stroke="#FF4b4b" stroke-width="2"/>
    <!-- Nose Cone -->
    <path d="M30 20 L38 35 H22 L30 20 Z" fill="#FF4b4b" stroke="#FF4b4b" stroke-width="1"/>
    <!-- Fins -->
    <path d="M22 75 L14 88 H22 V75 Z" fill="#FF0000" stroke="#FF4b4b" stroke-width="1"/>
    <path d="M38 75 L46 88 H38 V75 Z" fill="#FF0000" stroke="#FF4b4b" stroke-width="1"/>
    <!-- Engine Nozzle -->
    <path d="M26 85 L24 92 H36 L34 85" fill="#333"/>
    </svg>
    """)

    for o in orders:
        if o.get('health') is not None:
            pid = o['product_id']
            health = o['health']
            price_disp = f"${o['current_price']:,.2f}"
            tp_disp = o['tp_price']
            sl_disp = o['sl_price']
            val_disp = o.get('mission_value', 'N/A')
            upside_disp = o.get('upside', 'N/A')
            age_disp = o.get('age', 'N/A')
            side = o.get('side', 'BUY')
            
            # Logic
            # BUY = "Staging for Liftoff" (Orange/Yellow), Vertical Rocket on Launchpad
            # SELL = "In Flight" (Cyan/Red), faces left if retreating (Health < 50)
            
            staging_class = ""
            
            if side == 'BUY':
                 is_retreating = False 
                 status_color = '#ffaa00' # Orange for "Liftoff Prep"
                 status_text = 'STAGING'
                 staging_class = "staging"
                 
                 # Simplified SVG - No patterns/defs to avoid rendering bugs
                 svg_ship_staging = textwrap.dedent("""
                 <svg viewBox="0 0 60 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <!-- Launch Tower Structure (Left Side) -->
                    <!-- Main Truss -->
                    <rect x="2" y="20" width="12" height="80" stroke="#666" stroke-width="2"/>
                    <!-- Cross Bracing (Manual lines instead of pattern) -->
                    <path d="M2 20 L14 30 M2 30 L14 40 M2 40 L14 50 M2 50 L14 60 M2 60 L14 70 M2 70 L14 80 M2 80 L14 90 M2 90 L14 100" stroke="#444" stroke-width="1"/>
                    
                    <!-- Arms -->
                    <line x1="14" y1="35" x2="28" y2="35" stroke="#888" stroke-width="3"/> <!-- Upper Arm -->
                    <line x1="14" y1="75" x2="24" y2="75" stroke="#888" stroke-width="3"/> <!-- Lower Arm -->
                    
                    <!-- Rocket Body (Vertical) -->
                    <path d="M30 20 L38 35 V85 H22 V35 L30 20 Z" fill="#E0E0E0" stroke="#FFF" stroke-width="2"/>
                    
                    <!-- Nose Cone Detail -->
                    <path d="M30 20 L38 35 H22 L30 20 Z" fill="#FFD700" stroke="#FFD700" stroke-width="1"/>
                    
                    <!-- Fins (Bigger/Brighter) -->
                    <path d="M22 75 L14 88 H22 V75 Z" fill="#FF4500" stroke="#FFF" stroke-width="1"/>
                    <path d="M38 75 L46 88 H38 V75 Z" fill="#FF4500" stroke="#FFF" stroke-width="1"/>
                    
                    <!-- Engine Nozzle -->
                    <path d="M26 85 L24 92 H36 L34 85" fill="#333"/>
                    
                    <!-- Launch Pad Base -->
                    <rect x="10" y="92" width="40" height="8" fill="#555" stroke="#333"/>
                    
                    <!-- Venting Smoke (Simple opacity pulse) -->
                     <circle cx="38" cy="94" r="4" fill="white" fill-opacity="0.8">
                        <animate attributeName="r" values="4;6;4" dur="2s" repeatCount="indefinite"/>
                        <animate attributeName="fill-opacity" values="0.8;0.2;0.8" dur="2s" repeatCount="indefinite"/>
                    </circle>
                 </svg>
                 """)
                 # Force strip all indentation to prevent Markdown code block triggers
                 ship_icon = "".join([line.strip() for line in svg_ship_staging.split('\n')])
                 plume_style = "" # Handled inside SVG or disabled
                 
            else:
                 # SELL (Legacy Logic)
                 # Determine direction based on price history
                 trend_direction = 'RIGHT' # Default
                 
                 # Initialize price history if needed
                 if 'price_history' not in st.session_state:
                     st.session_state.price_history = {}
                 
                 prev_data = st.session_state.price_history.get(pid, {})
                 prev_price = prev_data.get('price', 0)
                 prev_trend = prev_data.get('trend', 'RIGHT')
                 
                 current_price = o['current_price']
                 
                 if current_price > prev_price:
                     trend_direction = 'RIGHT'
                 elif current_price < prev_price:
                     trend_direction = 'LEFT'
                 else:
                     trend_direction = prev_trend # Keep previous direction if price is unchanged
                 
                 # Update history
                 st.session_state.price_history[pid] = {
                     'price': current_price,
                     'trend': trend_direction
                 }
                 
                 is_retreating = trend_direction == 'LEFT'
                 status_color = '#00f3ff' if health > 50 else '#ffaa00' if health > 20 else '#ff4b4b'
                 status_text = 'STABLE' if health > 50 else 'UNSTABLE' if health > 20 else 'CRITICAL'
                 ship_icon = svg_ship_alert if is_retreating else svg_ship_normal
                 # Create robust single-line SVG string
                 ship_icon = "".join([line.strip() for line in ship_icon.split('\n')])
                 
                 # Default plume (Blue thrust)
                 plume_style = ""
            
            retreat_class = "retreat" if is_retreating else ""
            
            # Visual Clamp: Prevent ship from being clipped at 0% or 100%
            # The ship is centered on 'left', so 0% clips half the ship.
            # We map 0-100 logic scale to roughly 4-96 visual scale.
            visual_pos = max(4, min(96, health))
            
            # Dedent the HTML content to prevent it from being rendered as a code block
            # We use distinct strings concatenated to avoid indentation issues entirely
            html_content = f"""
<div class="hud-container">
<div class="mission-header">
<span class="mission-title">{pid} <span style="font-size: 0.6em; opacity: 0.7;">[{side}]</span></span>
<span class="mission-status" style="color: {status_color}; border-color: {status_color}; text-shadow: 0 0 5px {status_color};">
STATUS: {status_text}
</span>
</div>
<div class="flight-deck">
<div class="starfield"></div>
<div class="marker sl"><span class="marker-label" style="color: #ff4b4b;">SL {sl_disp}</span></div>
<div class="marker tp"><span class="marker-label" style="color: #00ff00;">TP {tp_disp}</span></div>
<div class="ship-container {retreat_class} {staging_class}" style="left: {visual_pos}%;">
<div class="ship-svg">{ship_icon}</div>
<div class="engine-plume" style="{plume_style}"></div>
<div class="price-tag">{price_disp}</div>
<div class="diagnostic-overlay">
<div class="diag-row"><span>VELOCITY:</span> <span>STABLE</span></div>
<div class="diag-row"><span>HULL:</span> <span>{health}%</span></div>
<div class="diag-row"><span>DISTANCE:</span> <span>{(100-health) if not is_retreating else health}m</span></div>
</div>
</div>
</div>
<div class="telemetry-grid">
<div class="t-module"><span class="t-label">MISSION TIME</span><span class="t-value" style="color: #4facfe">{age_disp}</span></div>
<div class="t-module"><span class="t-label">CURRENT ALT</span><span class="t-value">{price_disp}</span></div>
<div class="t-module"><span class="t-label">PAYLOAD VAL</span><span class="t-value" style="color: #ffd700">{val_disp}</span></div>
<div class="t-module"><span class="t-label">EST. YIELD</span><span class="t-value" style="color: {status_color}">{upside_disp}</span></div>
</div>
</div>
"""
            st.markdown(html_content, unsafe_allow_html=True)

# --- Mission History Section ---
if client:
    st.markdown("---")
    st.markdown("### Mission Hall of Fame (Recent Landings)")
    
    history_missions = get_mission_history(client, limit=5)
    
    if history_missions:
        for h in history_missions:
                # determine styles based on status
                status = h.get('status', 'UNKNOWN')
                
                # Defaults (Success)
                border_color = "#ffd700"
                text_color = "#ffd700"
                header_text = f"CONFIRMED LANDING: {h['product']}"
                status_text = "SUCCESS"
                
                if status == 'CRASH LANDED':
                    border_color = "#ff4b4b"     # Red
                    text_color = "#ff4b4b"
                    header_text = f"CRASH LANDING: {h['product']}"
                    status_text = "FAILED"
                elif status == 'ABORTED':
                    border_color = "#ffaa00"     # Orange
                    text_color = "#ffaa00" 
                    header_text = f"MISSION ABORTED: {h['product']}"
                    status_text = "ABORTED"
                
                # Simplified Card for "Landed" missions
                hist_html = f"""
<div class="hud-container" style="border-color: {border_color}; opacity: 0.9;">
<div class="mission-header" style="border-bottom: 1px dotted {border_color}; margin-bottom: 5px;">
<span class="mission-title" style="color: {text_color}; font-size: 1.2em;">{header_text}</span>
<span class="mission-status" style="color: {text_color}; border-color: {border_color}; text-shadow: 0 0 5px {border_color};">{status_text}</span>
</div>
<div class="telemetry-grid" style="grid-template-columns: repeat(5, 1fr); border: none; padding-top: 5px;">
<div class="t-module"><span class="t-label">TOUCHDOWN TIME</span><span class="t-value">{h['time']}</span></div>
<div class="t-module"><span class="t-label">PAYLOAD SIZE</span><span class="t-value">{h['size']}</span></div>
<div class="t-module"><span class="t-label">FINAL PRICE</span><span class="t-value">{h['price']}</span></div>
<div class="t-module"><span class="t-label">MISSION FEES</span><span class="t-value" style="color: #ffaa00">{h['fees']}</span></div>
<div class="t-module"><span class="t-label">NET PROFIT</span><span class="t-value" style="color: {'#00ff00' if h.get('raw_profit', 0) >= 0 else '#ff4b4b'}">{h['profit']}</span></div>
</div>
</div>
"""
                st.markdown(hist_html, unsafe_allow_html=True)
    else:
        st.caption("No recent missions found in flight logs.")

# --- Auto-Refresh heres (Bottom of Script) ---
if not orders:
     st.caption("Auto-refreshing in 30 seconds...")
else:
     st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')} | Auto-refreshing in 30s...")

time.sleep(30)
st.rerun()
