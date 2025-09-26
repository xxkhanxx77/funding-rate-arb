#!/usr/bin/env python3
from legacy.funding_bot import AsterDexFundingBot
from decimal import Decimal
import logging

logging.basicConfig(level=logging.INFO)

def perfect_hedge():
    """Adjust position to achieve perfect 100% hedge"""

    # Current positions from monitor
    current_spot = Decimal('45.66657550')
    current_futures_short = Decimal('45.59')

    # Calculate needed adjustment (round to 0.01 step size)
    adjustment_needed = (current_spot - current_futures_short).quantize(Decimal('0.01'))

    print(f"=== Perfect Hedge Adjustment ===")
    print(f"Current Spot ASTER: {current_spot}")
    print(f"Current Futures Short: {current_futures_short}")
    print(f"Adjustment needed: +{adjustment_needed} ASTER short")
    print(f"Target Hedge Ratio: 100.00%")

    if adjustment_needed <= Decimal('0.01'):
        print("✅ Already perfectly hedged!")
        return True

    # Create bot instance
    bot = AsterDexFundingBot(capital_usd=Decimal('20'), batch_quote=Decimal('20'))

    try:
        # Check if adjustment meets minimum notional (~$5)
        aster_price = Decimal('2.0')  # Approximate price
        notional_value = adjustment_needed * aster_price

        if notional_value < Decimal('5.0'):
            # Round up to meet minimum notional
            min_qty_needed = (Decimal('5.0') / aster_price).quantize(Decimal('0.01'))
            print(f"Minimum notional $5 requires {min_qty_needed} ASTER")
            print(f"Using {min_qty_needed} instead of {adjustment_needed}")
            adjustment_needed = min_qty_needed

        print(f"\nOpening additional {adjustment_needed} ASTER short...")

        # Place additional short order
        order = bot._place_futures_market_short(adjustment_needed)

        print(f"✅ Adjustment completed!")
        print(f"Order ID: {order.get('orderId')}")
        print(f"Executed Qty: {order.get('executedQty')}")
        print(f"Fill Price: ${order.get('avgPrice', 'N/A')}")

        # Calculate new hedge ratio
        new_futures_total = current_futures_short + Decimal(str(order.get('executedQty', adjustment_needed)))
        new_hedge_ratio = new_futures_total / current_spot

        print(f"\n=== Updated Position ===")
        print(f"Spot ASTER: {current_spot}")
        print(f"Futures Short: {new_futures_total}")
        print(f"Hedge Ratio: {new_hedge_ratio:.4f} ({new_hedge_ratio*100:.2f}%)")

        if new_hedge_ratio >= Decimal('0.999'):
            print("🎯 Perfect hedge achieved! (99.9%+)")

        return True

    except Exception as e:
        print(f"❌ Error adjusting position: {e}")
        return False

if __name__ == "__main__":
    perfect_hedge()
