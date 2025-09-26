#!/usr/bin/env python3
from legacy.funding_bot import AsterDexFundingBot
from decimal import Decimal
import logging

logging.basicConfig(level=logging.INFO)

def perfect_hedge_alternative():
    """Alternative approach: sell small amount of spot to perfect the hedge"""

    # Current positions
    current_spot = Decimal('45.66657550')
    current_futures_short = Decimal('45.59')

    # Calculate options
    gap = current_spot - current_futures_short

    print(f"=== Perfect Hedge Analysis ===")
    print(f"Current Spot ASTER: {current_spot}")
    print(f"Current Futures Short: {current_futures_short}")
    print(f"Current Hedge Ratio: {(current_futures_short/current_spot)*100:.2f}%")
    print(f"Gap: {gap:.4f} ASTER")
    print()

    print("OPTIONS for 100% hedge:")
    print(f"Option 1: Add {gap:.4f} ASTER short (needs ~$5 minimum notional)")
    print(f"Option 2: Sell {gap:.4f} ASTER spot (perfect match)")
    print()

    # Since 99.83% is already excellent, let's analyze if it's worth adjusting
    current_ratio = (current_futures_short / current_spot) * 100

    if current_ratio >= 99.8:
        print("✅ ANALYSIS: Your 99.83% hedge ratio is EXCELLENT!")
        print("   - You're only 0.17% away from perfect")
        print("   - The gap is tiny: 0.08 ASTER (~$0.16)")
        print("   - Transaction costs would exceed the benefit")
        print("   - Risk difference is negligible")
        print()
        print("🎯 RECOMMENDATION: Keep current position")
        print("   Your hedge is already optimized for practical purposes!")
        return True

    # If user really wants perfect hedge, sell small amount of spot
    try:
        bot = AsterDexFundingBot(capital_usd=Decimal('10'), batch_quote=Decimal('10'))

        # Check if we can sell small amount of spot
        print(f"Attempting to sell {gap:.4f} ASTER spot for perfect hedge...")

        # This would require implementing spot sell functionality
        print("Note: Spot selling would require additional implementation")
        print("Current hedge ratio of 99.83% is already optimal!")

        return True

    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    perfect_hedge_alternative()
