# QuantumEdge AI Trading Agent

QuantumEdge is a modular, autonomous US equities trading agent designed to run against Alpaca paper trading by default and Alpaca live trading when explicitly enabled. It combines technical strategies, hard risk controls, Random Forest signal scoring, SQLite performance tracking, and a Streamlit dashboard.

> **Direct answer:** yes, this code can place real broker orders through Alpaca when `LIVE_MODE=true`, the live Alpaca URL is configured, and `LIVE_TRADING_ACK=I_UNDERSTAND_REAL_MONEY_RISK` is set. The default is paper/test mode so nobody accidentally risks real money. Real-money trading can lose capital.

## Features

- **Market data:** yfinance OHLCV ingestion with RSI, MACD, Bollinger Bands, EMA 9/21/50, ATR, volume spike detection, and pre-market gap scanning.
- **Strategies:** momentum breakout, mean reversion, and EMA trend following.
- **Risk controls:** 2% daily loss hard stop, 5% max position size, max 3 concurrent positions, no first/last 15-minute trading, VIX halt over 30, Kelly sizing, and 3:45 PM ET liquidation.
- **AI signal enhancer:** Random Forest confidence scoring with weekly retraining support.
- **Execution:** Alpaca smart limit/bracket orders, take-profit and stop-loss protection, retry logic, stale-order cancellation, partial-fill status checks, and SQLite order logs.
- **Dashboard:** dark Streamlit UI with equity, PnL, trades, orders, risk metrics, and control buttons.

## Project layout

```text
QuantumEdge/
├── ai_signal_enhancer.py
├── config.py
├── dashboard.py
├── data_engine.py
├── execution_engine.py
├── logging_utils.py
├── main.py
├── portfolio_tracker.py
├── risk_manager.py
├── strategy_engine.py
├── tests/
├── requirements.txt
├── .env.example
└── setup.sh
```

## Quick start

### 1. Create and activate a virtual environment

```bash
cd QuantumEdge
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows PowerShell
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Alternatively, on macOS/Linux:

```bash
./setup.sh
```

### 3. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and add your Alpaca paper API key and secret.

## How to get Alpaca API keys

1. Create an Alpaca account at `https://alpaca.markets/`.
2. Open the **Paper Trading** dashboard.
3. Generate or copy your **API Key** and **Secret Key**.
4. Paste them into `.env`:

```env
ALPACA_API_KEY=your_paper_key_here
ALPACA_SECRET_KEY=your_paper_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
LIVE_MODE=false
```

The default `ALPACA_DATA_FEED=iex` is compatible with free-tier market data.

## Run the dashboard

```bash
streamlit run dashboard.py
```

Open the browser URL printed by Streamlit. With valid Alpaca credentials, the **Start Bot** button starts the APScheduler trading service inside the Streamlit process; **Stop Bot** stops it; **Close All Positions** sends an Alpaca liquidation request when the dashboard-started bot is running.

## Run the autonomous bot service

In a separate terminal:

```bash
python main.py
```

The service starts these scheduled jobs:

- Market scan every 5 minutes.
- Risk check every 1 minute.
- Daily performance report at 4:30 PM ET.
- Model retrain every Sunday.

## Switching from paper to live trading

Only switch after extensive paper-trading validation.

1. Replace your paper credentials with live Alpaca credentials.
2. Set the live base URL.
3. Set `LIVE_MODE=true`.
4. Set `LIVE_TRADING_ACK=I_UNDERSTAND_REAL_MONEY_RISK`. This second flag is intentional friction to prevent accidental live trading.

```env
ALPACA_API_KEY=your_live_key_here
ALPACA_SECRET_KEY=your_live_secret_here
ALPACA_BASE_URL=https://api.alpaca.markets
LIVE_MODE=true
LIVE_TRADING_ACK=I_UNDERSTAND_REAL_MONEY_RISK
```

When live mode is enabled, QuantumEdge logs a critical warning at startup and places real Alpaca orders from `main.py`. Buy entries use bracket orders by default when the strategy supplies both take-profit and stop-loss percentages. You remain responsible for all live-trading risk.

## Testing

```bash
pytest
```

The included unit tests cover the risk manager and strategy engine.

## Operational notes

- Logs are written to the console and `logs/trading.log`.
- SQLite data is stored at `data/quantumedge.db` by default.
- Strategy loss streaks pause any strategy that loses 3 trades in a row during the day.
- The dashboard can start the bot inside the Streamlit process, but many operators still prefer running `python main.py` as a dedicated service for production reliability.

## Disclaimer

This project is software, not financial advice. Markets are risky and automated trading can lose money quickly. Always test in paper mode first and monitor live systems carefully.
