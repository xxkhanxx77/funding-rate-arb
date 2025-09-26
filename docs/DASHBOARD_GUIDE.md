# AsterDex Position Monitoring Dashboard

A comprehensive real-time monitoring dashboard for your AsterDex positions, built on your existing funding bot infrastructure.

## Features

### 🎛️ Real-Time Dashboard
- **Portfolio Overview**: Total portfolio value, spot/futures allocation
- **Risk Metrics**: Leverage, exposure, risk level assessment
- **Position Monitoring**: All open futures positions with P&L
- **Funding Rates**: Current funding rates for key symbols
- **Hedging Efficiency**: Analysis of spot/futures hedge ratios
- **Funding Payments**: Historical funding fee receipts

### 🔄 Auto-Refresh
- Updates every 30 seconds automatically
- Manual refresh button available
- Responsive design for desktop and mobile

## Quick Start

1. **Start the server**:
   ```bash
   uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Access the dashboard**:
   ```
   http://localhost:8000/dashboard
   ```

3. **API Documentation**:
   ```
   http://localhost:8000/docs
   ```

## API Endpoints

### Dashboard
- `GET /dashboard` - Main monitoring dashboard (HTML)

### Account Information
- `GET /api/monitor/summary` - Complete account summary
- `GET /api/monitor/balance/spot` - Spot account balance
- `GET /api/monitor/balance/futures` - Futures account balance

### Positions & P&L
- `GET /api/monitor/positions` - Current futures positions
- `GET /api/monitor/pnl` - Position P&L analysis
- `GET /api/monitor/risk` - Risk metrics and leverage

### Funding & Efficiency
- `GET /api/monitor/hedging` - Hedging efficiency analysis
- `GET /api/monitor/funding-payments?days=7` - Recent funding payments

## Dashboard Sections

### 📊 Portfolio Overview
- **Total Portfolio Value**: Combined spot + futures USD value
- **Asset Allocation**: Breakdown of spot vs futures allocation
- **Balance Distribution**: Visual representation of holdings

### ⚖️ Risk Metrics
- **Effective Leverage**: Overall portfolio leverage
- **Risk Level**: Automatic risk assessment (LOW/MEDIUM/HIGH/EXTREME)
- **Total Exposure**: Notional value of all positions
- **Margin Utilization**: Margin usage efficiency

### 📈 Current Positions
- **All Open Positions**: Real-time position data
- **P&L Tracking**: Unrealized profits/losses
- **Entry vs Mark Price**: Position performance
- **Position Sizing**: Quantity and notional values

### 💰 Funding Rates
- **Current Rates**: Live funding rates for monitored symbols
- **Rate History**: Funding rate trends
- **Positive/Negative Indicators**: Color-coded rate display

### 🎯 Hedging Efficiency
- **Hedge Ratios**: Spot vs futures position ratios
- **Over/Under Hedged**: Position imbalance alerts
- **Average Efficiency**: Portfolio-wide hedge performance

### 💸 Recent Funding Payments
- **Payment History**: Last 7 days of funding receipts
- **Symbol Breakdown**: Payments by trading pair
- **Total Earnings**: Cumulative funding income

## Color Coding

- 🟢 **Green**: Positive values, good metrics, low risk
- 🟡 **Yellow**: Warning levels, medium risk
- 🔴 **Red**: Negative values, high risk, alerts

## Technical Details

### Data Sources
- **Spot API**: `https://sapi.asterdex.com`
- **Futures API**: `https://fapi.asterdex.com`
- Uses same authentication as your funding bot

### Security
- API keys from environment variables or defaults
- Same security model as existing bot
- Local monitoring (no external data transmission)

### Performance
- Efficient API calls with error handling
- Caching where appropriate
- Lightweight frontend with vanilla JavaScript

## Troubleshooting

### Common Issues

1. **"Loading..." persists**:
   - Check API key/secret configuration
   - Verify network connectivity to AsterDex
   - Check browser console for errors

2. **Empty positions/balances**:
   - Ensure you have active positions
   - Verify API permissions include account data

3. **Funding data missing**:
   - Some symbols may not have funding rates
   - Check if symbols are actively traded

### API Testing

Test individual endpoints:
```bash
# Check account summary
curl http://localhost:8000/api/monitor/summary

# Check positions
curl http://localhost:8000/api/monitor/positions

# Check risk metrics
curl http://localhost:8000/api/monitor/risk
```

## Integration with Bot

The dashboard shares the same API infrastructure as your funding bot:
- Uses identical authentication
- Same AsterDex API endpoints
- Compatible with bot operations
- No interference with trading activities

Monitor your positions in real-time while your funding bot operates!
