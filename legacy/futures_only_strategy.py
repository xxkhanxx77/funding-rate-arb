#!/usr/bin/env python3
"""
Futures-Only Funding Strategy
For users who only have futures balance
"""

import argparse
import json
from decimal import Decimal
from legacy.funding_bot import configure_logging
from monitor import AsterDexMonitor

def check_futures_only_feasibility():
    """Check if futures-only strategy is possible"""
    print("🔍 Analyzing Futures-Only Strategy")
    print("=" * 40)

    try:
        monitor = AsterDexMonitor()
        futures_balance = monitor.get_futures_balance()
        positions = monitor.get_futures_positions()

        available = float(futures_balance.get("availableBalance", 0))

        print(f"💰 Futures Available Balance: ${available:.2f}")
        print(f"📊 Current Positions: {len(positions)}")

        if positions:
            print("\n📈 Existing Positions:")
            for pos in positions:
                symbol = pos.get("symbol", "")
                amt = float(pos.get("positionAmt", 0))
                side = "LONG" if amt > 0 else "SHORT"
                pnl = float(pos.get("unRealizedProfit", 0))
                print(f"  {symbol}: {side} {abs(amt):.4f} (PnL: ${pnl:.2f})")

        # Calculate strategy options
        print(f"\n🎯 Strategy Options:")

        if available >= 20:
            print(f"✅ Option 1: Open balanced positions")
            print(f"   - Long ASTERUSDT: Use ${available/2:.0f}")
            print(f"   - Short another pair: Use ${available/2:.0f}")
            print(f"   - Earn funding rate difference")

        if available >= 10:
            print(f"✅ Option 2: Single direction trade")
            print(f"   - Check funding rate")
            print(f"   - Go long if rate is positive")
            print(f"   - Go short if rate is negative")

        if available < 10:
            print(f"❌ Insufficient balance for safe trading")
            print(f"   - Minimum recommended: $10")
            print(f"   - Current available: ${available:.2f}")

        return available >= 10

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def execute_futures_long(amount, symbol="ASTERUSDT"):
    """Execute a futures long position"""
    print(f"\n🚀 Opening Long Position")
    print(f"Symbol: {symbol}")
    print(f"Amount: ${amount}")

    try:
        # This would require modifying the bot to work with futures-only
        # For now, provide manual instructions

        print(f"\n📋 Manual Execution Steps:")
        print(f"1. Go to AsterDex Futures Trading")
        print(f"2. Select {symbol}")
        print(f"3. Choose 'Long' / 'Buy'")
        print(f"4. Set amount: ~${amount}")
        print(f"5. Use Market order for immediate fill")
        print(f"6. Monitor funding rates every 8 hours")

        print(f"\n💡 Why this works:")
        print(f"- If funding rate > 0: Shorts pay longs (you earn)")
        print(f"- If funding rate < 0: Longs pay shorts (you pay)")
        print(f"- Strategy: Hold long when rates are positive")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Futures-Only Funding Strategy")
    parser.add_argument("--check", action="store_true", help="Check feasibility")
    parser.add_argument("--long", type=float, help="Open long position with amount")
    parser.add_argument("--symbol", default="ASTERUSDT", help="Trading symbol")

    args = parser.parse_args()
    configure_logging("ERROR")

    if args.check:
        feasible = check_futures_only_feasibility()
        if feasible:
            print(f"\n✅ Futures-only strategy is possible!")
            print(f"🎯 Next: Run with --long <amount>")
        else:
            print(f"\n❌ Not enough balance for futures-only strategy")
            print(f"💡 Consider transferring funds to spot for full strategy")

    elif args.long:
        print(f"🎯 Futures-Only Long Strategy")
        print(f"=" * 35)

        # Check funding rate first
        try:
            monitor = AsterDexMonitor()
            funding_info = monitor.get_funding_info([args.symbol])

            if funding_info:
                rate = funding_info[0].get("premium_index", {}).get("lastFundingRate", "0")
                rate_percent = float(rate) * 100

                print(f"📊 Current {args.symbol} Funding Rate: {rate_percent:.4f}%")

                if rate_percent > 0.01:
                    print(f"✅ Positive rate - Good for long positions")
                    execute_futures_long(args.long, args.symbol)
                elif rate_percent < -0.01:
                    print(f"❌ Negative rate - Long positions will pay funding")
                    print(f"💡 Consider waiting for positive rates")
                else:
                    print(f"⚠️  Near-zero rate - Minimal funding income expected")

        except Exception as e:
            print(f"❌ Error checking funding rate: {e}")

    else:
        parser.print_help()
        print(f"\n💡 Quick start:")
        print(f"   python {parser.prog} --check")
        print(f"   python {parser.prog} --long 50")

if __name__ == "__main__":
    main()
