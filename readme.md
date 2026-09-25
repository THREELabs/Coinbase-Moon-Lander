# Coinbase Moon Lander & Market Kombat

<div align="center">

![Coinbase Moon Lander](https://unbound-riddle-msyk.here.now/moon-lander.jpg)

**Next-Gen Visualizer for your Coinbase Advanced Trade Orders.**

*Transform boring order books into epic deep-space missions and retro arcade fighting bouts!*

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Coinbase API](https://img.shields.io/badge/Coinbase-Advanced_Trade-0052FF?style=for-the-badge&logo=coinbase&logoColor=white)](https://www.coinbase.com/advanced-trade)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

</div>

---

## 🎨 Dual Interactive Themes

Switch on the fly between two completely distinct visual experiences via the sidebar theme selector:

### 1. 🚀 Moon Lander (Classic Space Edition)
Visualizes your active crypto trades as spacecraft navigating deep space:
- **STAGING (Buy Orders)**: Rockets seated on launchpads awaiting price drop for ignition.
- **IN FLIGHT (Sell & Bracket Orders)**: Ships surging rightward toward Moon touchdown (Take Profit) or retro-thrusting leftward (Stop Loss).
- **Radar Obstacles & Beacons**: Overhead UFO motherships represent order book Ask resistance walls; glowing stars below represent Bid support order floors.
- **Mission Hall of Fame**: Log of successful touchdowns and emergency crash landings.

<br>

<div align="center">

![Market Kombat](https://chilly-huckle-48mb.here.now/market-kombat.jpg)

</div>

### 2. 🥊 Market Kombat (Arcade Fighter Edition)
Step into an arcade neon arena where your crypto trades engage in 16-bit martial arts combat:
- **The Bull [Long Fighter]**: Represents your trade position. Advances with jab/cross strikes, power aura, and dragon uppercuts when winning.
- **The Bear [Boss]**: The Take Profit resistance boss with claw swipes, head stomps, and ground pounds.
- **Dual Dynamic Lifebars**: Direct health gauges (100% = K.O. strike at TP; 0% = Stop Loss fatality).
- **Hadouken Fireballs & Spirit Shields**: Order book depth rendered as airborne projectiles hurled across the arena.
- **Clash Sparks & Finishers**: Dynamic hit impact sparks, "FINISH HIM!" rage modes, and Kombat Hall of Fame victory logs.

---

## ⚡ Features

- **Live Coinbase Integration**: Direct streaming of real-time prices, order books, and fill status via `coinbase-advanced-py`.
- **🕹️ Instant Demo Simulation**: Test-drive both engines with zero API keys required using the built-in realistic price-tick simulator.
- **Responsive Mobile HUD**: Optimized for all viewports from 4K desktop screens down to smartphones without overlapping text.
- **Hall of Fame History**: Automatically parses filled orders, calculating gross proceeds, execution fees, and net PnL.

---

## 🚀 Quickstart & Setup

### Prerequisites
- Python 3.9+
- [Coinbase Advanced Trade](https://www.coinbase.com/advanced-trade) API key (View permissions recommended)

### 1. Clone & Install
```bash
git clone https://github.com/THREELabs/Coinbase-Moon-Lander.git
cd Coinbase-Moon-Lander
pip install -r requirements.txt
```

### 2. Configure Credentials (Optional)
You can enter keys directly in the web UI, or create a `.env` file in the root directory:
```bash
CB_API_KEY="your_coinbase_api_key"
CB_API_SECRET="your_coinbase_api_secret"
```

*For Streamlit Cloud deployments, add `CB_API_KEY` and `CB_API_SECRET` to your application's Secrets console.*

### 3. Launch the Application
```bash
streamlit run coinbase-moon-lander.py
```
Open your browser at `http://localhost:8501` or your computer network URL.

---

## 🎮 How to Play

1. **Select Theme**: Use the sidebar radio toggle to select **🚀 Moon Lander** or **🥊 Market Kombat**.
2. **Demo or Live**: Toggle **🕹️ Demo Simulation Mode** for immediate arcade preview or input Coinbase API keys for real trading radar.
3. **Analyze Depth**: Watch Asks and Bids dynamically materialize as resistance obstacles (UFOs / Fireballs) and support cushions (Stars / Shields).

---

*Disclaimer: This project is an independent open-source trade visualization tool and is not officially affiliated with Coinbase. Always verify order execution directly on the official Coinbase exchange.*
