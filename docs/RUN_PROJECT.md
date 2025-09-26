# 🚀 How to Run the AsterDex Funding Bot Project

## 📋 Quick Start (Recommended)

### Option 1: Using the Startup Script
```bash
cd /Users/admin/Desktop/hobbies/research/funding-fee-bot
# (ครั้งแรก) คัดลอกไฟล์ตัวอย่างแล้วแก้ไขค่าจริง
cp .env.example .env
# แก้ไข .env ด้วย API key/secret ของคุณ

./scripts/start_server.sh
# หรือใช้ `make run-server` เพื่อรันตรงจากโค้ด (ต้องโหลด .env เอง)
```

### Option 2: Manual Startup
```bash
cd /Users/admin/Desktop/hobbies/research/funding-fee-bot

# Load environment variables (หรือใช้ `set -a; source .env; set +a`)
set -a
source .env
set +a

# Start server (recommended)
uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
```

## 🎯 What You'll See

### Server Startup Display:
```
=== ASTERDEX Account Status on Startup ===
Spot Holdings:
  USDT: 9.95483190
  ASTER: 45.66657550
Futures Positions:
  ASTERUSDT: -45.59 (PnL: $7.71787000)
Strategy: 🟢 Active
Health: HEALTHY
Hedge Ratio: 99.83%
Gap: 0.08 tokens (~$0.15)
Funding Accumulated (30d): $0.2215
Current Funding Rate: 0.0579%
Estimated APY: 88.4%
Realized APY (30d): 3.3%
=== ASTERDEX Ready ===
```

### Server URLs:
- **🏠 Main API**: http://0.0.0.0:8000
- **📚 Documentation**: http://0.0.0.0:8000/docs
- **📊 Live Status**: http://0.0.0.0:8000/monitor/asterdex/simple
- **💰 APY Analysis**: http://0.0.0.0:8000/apy/asterdex/simple

## 🔧 Configuration Options

### Environment Variables:
```bash
# API Credentials (Required)
export ASTERDEX_API_KEY="your_api_key"
export ASTERDEX_API_SECRET="your_api_secret"

# Trading Configuration (Optional)
export FUNDING_DEX="asterdex"
export FUNDING_CAPITAL="100"
export FUNDING_SPOT_SYMBOL="ASTERUSDT"
export FUNDING_FUTURES_SYMBOL="ASTERUSDT"
export FUNDING_BATCH_QUOTE="10"
export FUNDING_MODE="buy_spot_short_futures"
```

### Legacy Configuration File (`samples/bot_config.json`):
```json
{
  "dex": "asterdex",
  "capital": "100",
  "spot_symbol": "ASTERUSDT",
  "futures_symbol": "ASTERUSDT",
  "batch_quote": "10",
  "batch_delay": 1.0,
  "mode": "buy_spot_short_futures",
  "recv_window": 5000,
  "max_leverage": 1
}
```

## 🎮 Key API Endpoints

### Monitoring:
```bash
# Quick status check
curl "http://localhost:8000/monitor/asterdex/simple"

# APY analysis
curl "http://localhost:8000/apy/asterdex/simple"

# Health check
curl "http://localhost:8000/health"
```

### Bot Control:
```bash
# Start a funding bot
curl -X POST "http://localhost:8000/start" \
  -H "Content-Type: application/json" \
  -d '{"dex": "asterdex", "capital": "100", "spot_symbol": "ASTERUSDT"}'

# Check bot status
curl "http://localhost:8000/status/{job_id}"
```

## 🛠️ Troubleshooting

### Common Issues:

#### 1. **Port Already in Use**
```bash
# Kill existing server
lsof -ti:8000 | xargs kill -9

# Then restart
./scripts/start_server.sh
```

#### 2. **Missing Dependencies**
```bash
# Install dependencies
uv sync

# Or reinstall everything
uv install
```

#### 3. **API Credentials Error**
- Make sure `ASTERDEX_API_KEY` and `ASTERDEX_API_SECRET` are set
- Check that your API keys have futures trading permissions

#### 4. **Configuration Issues**
```bash
# Check current config
uv run python scripts/manage_config.py show

# Update config
uv run python scripts/manage_config.py json '{"capital": "100", "dex": "asterdex"}'
```

## 🔍 Monitoring Your Bot

### Real-time Status:
Visit http://localhost:8000/monitor/asterdex/simple to see:
```
ASTERDEX FUNDING BOT STATUS:
Strategy: 🟢 Active
Health: HEALTHY
Hedge Ratio: 99.83%

PORTFOLIO:
Total PnL: $7.72
Positions: 1
Available: $25.72

FUNDING:
Accumulated (7d): $0.2215
Accumulated (30d): $0.2215
```

### APY Analysis:
Visit http://localhost:8000/apy/asterdex/simple to see:
```
ASTER Funding APY Analysis (ASTERDEX):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current Funding Rate: 0.0579%
Daily Rate (3x): 0.1736%

ESTIMATED APY: 88.4%
Realized APY (30d): 3.3%
Realized APY (7d): 15.1%
```

## 📁 Project Structure
```
funding-fee-bot/
├── app/                    # ⭐ Core application package
│  └── server.py            # FastAPI multi-DEX server
├── dexes/                  # Multi-DEX architecture
├── docs/                   # Guides and reference material
├── legacy/                 # Archived single-DEX scripts
├── samples/                # Example configs/data (bot_config.json, etc.)
├── scripts/                # Operational helpers (start_server.sh, manage_config.py)
├── tests/                  # Test suite
├── config.py               # Compatibility shim -> app.config
├── Makefile                # Common commands
└── README.md               # Project overview
```

## 🎉 Success Indicators

✅ **Server starts without errors**
✅ **Shows your account status on startup**
✅ **API endpoints respond correctly**
✅ **Background monitoring runs every 30s**
✅ **APY calculations display properly**

## 🚨 Next Steps After Starting

1. **Monitor your positions**: Check http://localhost:8000/monitor/asterdex/simple
2. **Review APY performance**: Check http://localhost:8000/apy/asterdex/simple  
3. **Start a new bot** (if needed): Use the `/start` API endpoint
4. **Explore the API**: Visit http://localhost:8000/docs

Your funding bot is now running with full monitoring and APY analysis! 🎊
