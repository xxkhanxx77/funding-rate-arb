#!/usr/bin/env python3
"""
Small Capital Funding Strategy for AsterDex
Optimized for users with limited capital (e.g., 100 USDT spot + 100 USDT futures)
"""

import argparse
import json
import logging
from decimal import Decimal
from legacy.funding_bot import AsterDexFundingBot, configure_logging
from monitor import AsterDexMonitor

def analyze_minimum_requirements():
    """Analyze minimum trading requirements for ASTERUSDT"""
    try:
        # Initialize monitor to check current market conditions
        monitor = AsterDexMonitor()

        print("🔍 Analyzing AsterDex Trading Requirements...")
        print("=" * 50)

        # Get symbol info
        bot = AsterDexFundingBot(capital_usd=Decimal("20"), batch_quote=Decimal("20"))
        spot_info = bot._get_spot_symbol_info()
        futures_info = bot._get_futures_symbol_info()

        # Extract trading limits
        spot_step, spot_min_qty = bot._extract_step_and_min_qty(spot_info)
        futures_step, futures_min_qty = bot._extract_step_and_min_qty(futures_info)
        futures_min_notional = bot._extract_min_notional(futures_info)

        # Get current prices
        spot_price = bot._fetch_spot_price()
        futures_price = bot._fetch_futures_price()

        print(f"📊 ASTERUSDT Market Data:")
        print(f"  Spot Price:           ${spot_price}")
        print(f"  Futures Price:        ${futures_price}")
        print(f"  Price Difference:     ${abs(spot_price - futures_price):.6f}")

        print(f"\n📏 Trading Limits:")
        print(f"  Spot Min Qty:         {spot_min_qty} ASTER")
        print(f"  Spot Step Size:       {spot_step} ASTER")
        print(f"  Futures Min Qty:      {futures_min_qty} ASTER")
        print(f"  Futures Step Size:    {futures_step} ASTER")
        print(f"  Futures Min Notional: ${futures_min_notional}")

        # Calculate minimum capital requirements
        min_spot_value = spot_min_qty * spot_price
        min_futures_notional = max(futures_min_notional, futures_min_qty * futures_price)

        print(f"\n💰 Minimum Capital Requirements:")
        print(f"  Min Spot Order:       ${min_spot_value:.2f}")
        print(f"  Min Futures Order:    ${min_futures_notional:.2f}")
        print(f"  Total Minimum:        ${min_spot_value + min_futures_notional:.2f}")

        # Suggest optimal batch sizes for 200 USDT capital
        total_capital = Decimal("200")

        # Conservative approach: use 80% of capital, keep 20% as buffer
        usable_capital = total_capital * Decimal("0.8")  # 160 USDT

        # Calculate optimal batch sizes
        suggested_batches = [10, 20, 40]  # Different batch sizes to try

        print(f"\n🎯 Suggested Strategy for $200 Capital:")
        print(f"  Total Capital:        $200 (100 spot + 100 futures)")
        print(f"  Usable Capital:       ${usable_capital} (80% of total)")
        print(f"  Safety Buffer:        ${total_capital - usable_capital} (20% of total)")

        print(f"\n📋 Recommended Batch Configurations:")
        for batch_size in suggested_batches:
            num_batches = int(usable_capital / batch_size)
            if num_batches > 0:
                total_deployed = num_batches * batch_size
                print(f"  Option {batch_size}: ${batch_size} x {num_batches} batches = ${total_deployed} deployed")

        return {
            "spot_price": float(spot_price),
            "futures_price": float(futures_price),
            "min_spot_value": float(min_spot_value),
            "min_futures_notional": float(min_futures_notional),
            "suggested_batch_size": 20,  # Conservative recommendation
            "max_batches": int(usable_capital / 20)
        }

    except Exception as e:
        print(f"❌ Error analyzing requirements: {e}")
        return None

def create_small_capital_config(capital: int = 200, batch_size: int = 20):
    """Create optimized configuration for small capital"""
    return {
        "capital": str(capital * 0.8),  # Use 80% of capital
        "spot_symbol": "ASTERUSDT",
        "futures_symbol": "ASTERUSDT",
        "batch_quote": str(batch_size),
        "batch_delay": 2.0,  # Slower execution for safety
        "mode": "buy_spot_short_futures"  # Default mode
    }

def dry_run_strategy(config):
    """Perform a dry run to validate the strategy"""
    print("\n🧪 Performing Dry Run Validation...")
    print("=" * 40)

    try:
        capital = Decimal(config["capital"])
        batch_quote = Decimal(config["batch_quote"])

        # Calculate batches
        num_batches = int(capital / batch_quote)
        total_deployed = num_batches * batch_quote
        remaining = capital - total_deployed

        print(f"📊 Dry Run Results:")
        print(f"  Capital to Deploy:    ${capital}")
        print(f"  Batch Size:           ${batch_quote}")
        print(f"  Number of Batches:    {num_batches}")
        print(f"  Total Deployed:       ${total_deployed}")
        print(f"  Remaining Buffer:     ${remaining}")

        if num_batches == 0:
            print("❌ Error: Batch size too large for available capital")
            return False

        if remaining > batch_quote:
            print(f"⚠️  Warning: Large unused remainder (${remaining})")
            print(f"   Consider using batch size of ${int(capital / (num_batches + 1))}")

        # Estimate execution time
        total_time = num_batches * config["batch_delay"]
        print(f"  Estimated Runtime:    {total_time} seconds ({total_time/60:.1f} minutes)")

        return True

    except Exception as e:
        print(f"❌ Dry run failed: {e}")
        return False

def execute_small_capital_strategy(config, confirm=True):
    """Execute the funding strategy with small capital"""

    if confirm:
        print("\n⚠️  LIVE TRADING CONFIRMATION")
        print("=" * 40)
        print("This will place REAL orders on AsterDex!")
        print(f"Capital: ${config['capital']}")
        print(f"Batch Size: ${config['batch_quote']}")
        print(f"Mode: {config['mode']}")

        response = input("\nType 'YES' to proceed with live trading: ")
        if response != "YES":
            print("❌ Trading cancelled")
            return None

    try:
        print("\n🚀 Starting Live Trading...")
        print("=" * 30)

        # Create bot instance
        bot = AsterDexFundingBot(
            capital_usd=Decimal(config["capital"]),
            spot_symbol=config["spot_symbol"],
            futures_symbol=config["futures_symbol"],
            batch_quote=Decimal(config["batch_quote"]),
            batch_delay=config["batch_delay"],
            mode=config["mode"]
        )

        # Execute strategy
        result = bot.execute()

        print("\n✅ Trading Completed Successfully!")
        print("=" * 35)

        # Display summary
        spot_data = result.get("spot", {})
        futures_data = result.get("futures", {})

        print(f"📈 Execution Summary:")
        print(f"  Spot Orders:          {len(spot_data.get('orders', []))}")
        print(f"  Spot Quantity:        {spot_data.get('totalExecutedQty', '0')} ASTER")
        print(f"  Spot Value:           ${spot_data.get('totalQuoteSpent', '0')}")
        print(f"  Futures Orders:       {len(futures_data.get('orders', []))}")
        print(f"  Futures Quantity:     {futures_data.get('totalExecutedQty', '0')} ASTER")

        return result

    except Exception as e:
        print(f"❌ Trading failed: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Small Capital Funding Strategy for AsterDex")
    parser.add_argument("--analyze", action="store_true", help="Analyze minimum requirements")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run validation")
    parser.add_argument("--execute", action="store_true", help="Execute live trading")
    parser.add_argument("--capital", type=int, default=200, help="Total capital (USDT)")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size (USDT)")
    parser.add_argument("--mode", choices=["buy_spot_short_futures", "sell_spot_long_futures"],
                       default="buy_spot_short_futures", help="Trading mode")
    parser.add_argument("--no-confirm", action="store_true", help="Skip confirmation for live trading")

    args = parser.parse_args()

    configure_logging("INFO")

    if args.analyze:
        print("🔍 AsterDex Small Capital Analysis")
        print("=" * 50)
        requirements = analyze_minimum_requirements()
        if requirements:
            print(f"\n💡 Recommendation: Start with ${requirements['suggested_batch_size']} batch size")

    elif args.dry_run or args.execute:
        config = create_small_capital_config(args.capital, args.batch_size)
        config["mode"] = args.mode

        print(f"🎯 Small Capital Strategy Configuration")
        print("=" * 45)
        print(f"  Total Capital:        ${args.capital}")
        print(f"  Deployable Capital:   ${config['capital']}")
        print(f"  Batch Size:           ${config['batch_quote']}")
        print(f"  Mode:                 {config['mode']}")

        if dry_run_strategy(config):
            if args.execute:
                result = execute_small_capital_strategy(config, not args.no_confirm)
                if result:
                    print(f"\n💾 Saving results to small_capital_result.json")
                    with open("small_capital_result.json", "w") as f:
                        json.dump(result, f, indent=2)
            else:
                print("\n✅ Dry run completed successfully!")
                print("   Use --execute to run live trading")
        else:
            print("\n❌ Dry run failed - please adjust parameters")

    else:
        parser.print_help()
        print(f"\n💡 Quick start for your 200 USDT:")
        print(f"   python {parser.prog} --analyze")
        print(f"   python {parser.prog} --dry-run --capital 200 --batch-size 20")
        print(f"   python {parser.prog} --execute --capital 200 --batch-size 20")

if __name__ == "__main__":
    main()
