#!/usr/bin/env python3
"""
USDC-based funding strategy for AsterDex
For users who have USDC instead of USDT
"""

import argparse
from decimal import Decimal
from legacy.funding_bot import AsterDexFundingBot, configure_logging
import json

def check_usdc_pairs():
    """Check if ASTERUSDC trading pair exists"""
    print("🔍 Checking Available USDC Pairs")
    print("=" * 35)

    try:
        # Use a small bot instance to check exchange info
        bot = AsterDexFundingBot(capital_usd=Decimal("10"), batch_quote=Decimal("10"))

        # Get exchange info
        spot_info = bot._request(bot.spot_base_url, "/api/v1/exchangeInfo")
        futures_info = bot._request(bot.futures_base_url, "/fapi/v1/exchangeInfo")

        spot_symbols = [s.get("symbol", "") for s in spot_info.get("symbols", [])]
        futures_symbols = [s.get("symbol", "") for s in futures_info.get("symbols", [])]

        print("📊 Available Symbols:")
        print(f"Spot symbols: {', '.join(spot_symbols)}")
        print(f"Futures symbols: {', '.join(futures_symbols)}")

        # Check for USDC pairs
        usdc_spot = [s for s in spot_symbols if "USDC" in s]
        usdc_futures = [s for s in futures_symbols if "USDC" in s]

        print(f"\n💰 USDC Pairs:")
        print(f"Spot USDC pairs: {usdc_spot}")
        print(f"Futures USDC pairs: {usdc_futures}")

        # Check if ASTERUSDC exists
        if "ASTERUSDC" in spot_symbols and "ASTERUSDC" in futures_symbols:
            print(f"✅ ASTERUSDC pair available in both spot and futures!")
            return True
        else:
            print(f"❌ ASTERUSDC not available in both markets")
            # Suggest alternatives
            common_pairs = set(usdc_spot) & set(usdc_futures)
            if common_pairs:
                print(f"💡 Available USDC pairs in both markets: {list(common_pairs)}")
            return False

    except Exception as e:
        print(f"❌ Error checking pairs: {e}")
        return False

def run_usdc_strategy(capital=80, batch_size=20, symbol="ASTERUSDC"):
    """Run funding strategy with USDC pairs"""
    print(f"\n🚀 Running USDC Strategy")
    print("=" * 25)
    print(f"Symbol: {symbol}")
    print(f"Capital: ${capital}")
    print(f"Batch Size: ${batch_size}")

    try:
        # Create bot with USDC pair
        bot = AsterDexFundingBot(
            capital_usd=Decimal(str(capital)),
            spot_symbol=symbol,
            futures_symbol=symbol,
            batch_quote=Decimal(str(batch_size)),
            batch_delay=2.0,
            mode="buy_spot_short_futures"
        )

        print(f"✅ Bot configured for {symbol}")
        print(f"🎯 Executing strategy...")

        # Execute the strategy
        result = bot.execute()

        print(f"✅ Strategy completed successfully!")

        # Save results
        with open("usdc_strategy_result.json", "w") as f:
            json.dump(result, f, indent=2)

        # Display summary
        spot_data = result.get("spot", {})
        futures_data = result.get("futures", {})

        print(f"\n📊 Execution Summary:")
        print(f"Spot Orders: {len(spot_data.get('orders', []))}")
        print(f"Spot Quantity: {spot_data.get('totalExecutedQty', '0')} ASTER")
        print(f"Spot Spent: ${spot_data.get('totalQuoteSpent', '0')}")
        print(f"Futures Orders: {len(futures_data.get('orders', []))}")
        print(f"Futures Quantity: {futures_data.get('totalExecutedQty', '0')} ASTER")

        return result

    except Exception as e:
        print(f"❌ Strategy failed: {e}")

        # Try to provide helpful error info
        if "Balance is insufficient" in str(e):
            print(f"\n💡 Balance issue detected:")
            print(f"- Make sure you have {batch_size} USDC available in spot")
            print(f"- Check that {symbol} pair exists and is tradeable")
            print(f"- Verify minimum order sizes are met")

        return None

def main():
    parser = argparse.ArgumentParser(description="USDC-based funding strategy")
    parser.add_argument("--check", action="store_true", help="Check available USDC pairs")
    parser.add_argument("--execute", action="store_true", help="Execute USDC strategy")
    parser.add_argument("--capital", type=int, default=80, help="Capital to deploy")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size")
    parser.add_argument("--symbol", default="ASTERUSDC", help="Trading symbol")

    args = parser.parse_args()
    configure_logging("INFO")

    if args.check:
        available = check_usdc_pairs()
        if available:
            print(f"\n🎯 You can run:")
            print(f"python {parser.prog} --execute --capital 80 --batch-size 20")

    elif args.execute:
        print(f"🚀 USDC Funding Strategy")
        print("=" * 25)

        result = run_usdc_strategy(
            capital=args.capital,
            batch_size=args.batch_size,
            symbol=args.symbol
        )

        if result:
            print(f"\n💾 Results saved to usdc_strategy_result.json")
        else:
            print(f"\n❌ Strategy failed - check the error messages above")

    else:
        parser.print_help()
        print(f"\n💡 Your balance: 100 USDC (spot) + 100 USDC (futures)")
        print(f"Quick start:")
        print(f"  python {parser.prog} --check")
        print(f"  python {parser.prog} --execute --capital 80 --batch-size 20")

if __name__ == "__main__":
    main()
