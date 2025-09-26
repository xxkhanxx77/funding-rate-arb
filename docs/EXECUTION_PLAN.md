# AsterDex Funding Strategy - Execution Plan
## Your Balance: 100 USDT Spot + 100 USDT Futures

### ✅ Analysis Complete
- **Market Requirements**: ✅ PASSED
  - Minimum order: $5 (you have $200 total)
  - ASTERUSDT is actively traded
  - Spot price: ~$2.01, Futures: ~$2.02
  - Small spread indicates good arbitrage opportunity

### 🎯 Recommended Strategy

**Conservative Approach (Recommended)**:
```bash
# Deploy 160 USDT in 8 batches of 20 USDT each
uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 20
```

**Alternative Approaches**:
```bash
# More batches, smaller size (slower execution)
uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 10

# Fewer batches, larger size (faster execution)  
uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 40
```

### 📊 Expected Execution

**With 20 USDT batches**:
- 8 spot market buy orders ($20 each)
- 8 futures market sell orders (hedge)
- Total deployment: $160 USDT
- Safety buffer: $40 USDT (20%)
- Execution time: ~16 seconds

### 🔧 Step-by-Step Execution

1. **Pre-flight Check**:
   ```bash
   # Check your current balances
   uv run python -m legacy.dashboard_cli --section portfolio
   ```

2. **Final Validation**:
   ```bash
   # Run dry-run one more time
   uv run python -m legacy.small_capital_strategy --dry-run --capital 200 --batch-size 20
   ```

3. **Execute Strategy**:
   ```bash
   # LIVE TRADING - will ask for confirmation
   uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 20
   
   # Skip confirmation (advanced)
   uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 20 --no-confirm
   ```

4. **Monitor Results**:
   ```bash
   # Check positions after execution
   uv run python -m legacy.dashboard_cli --section positions
   
   # Check funding payments over time  
   uv run python -m legacy.dashboard_cli --section payments
   ```

### 💰 Expected Outcome

**Position Structure**:
- **Spot**: ~79.6 ASTER tokens (worth ~$160)
- **Futures**: -79.6 ASTER short position (hedged)
- **Net Exposure**: ~0 (market neutral)
- **Funding Income**: Depends on funding rates

**Capital Allocation**:
- Deployed: $160 (80%)
- Buffer: $40 (20%) - for margin, fees, market movements

### ⚠️ Risk Management

**Safety Features Built-in**:
- 20% capital buffer
- Market orders for immediate execution
- Position matching (spot qty = futures qty)
- Error handling and order validation

**What to Watch**:
- Funding rates (positive = you earn)
- Position balance (spot vs futures)
- Margin usage on futures side

### 🚨 Important Notes

1. **API Keys**: Ensure your API keys have spot + futures trading permissions
2. **Capital Distribution**: You need USDT in both spot and futures accounts
3. **Funding Schedule**: Funding occurs every 8 hours (check AsterDex schedule)
4. **Exit Strategy**: Run reverse mode to close positions:
   ```bash
   uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 20 --mode sell_spot_long_futures
   ```

### 🎯 Quick Start Commands

```bash
# 1. Check requirements
uv run python -m legacy.small_capital_strategy --analyze

# 2. Validate strategy  
uv run python -m legacy.small_capital_strategy --dry-run --capital 200 --batch-size 20

# 3. Execute (with confirmation)
uv run python -m legacy.small_capital_strategy --execute --capital 200 --batch-size 20

# 4. Monitor positions
uv run python -m legacy.dashboard_cli
```

### 📈 Success Metrics

**Immediate (Post-Execution)**:
- ✅ All orders filled successfully
- ✅ Spot and futures quantities match
- ✅ No failed transactions

**Ongoing (Daily/Weekly)**:
- 📈 Positive funding income accumulation  
- ⚖️ Maintained hedge ratio (>95%)
- 💰 Total return > holding USDT

Ready to start? Run the analysis command first, then proceed with the execution plan!