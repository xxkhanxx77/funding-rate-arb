#!/usr/bin/env python3
from legacy.funding_bot import AsterDexFundingBot
from decimal import Decimal
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def achieve_full_hedge():
    """Open additional futures short to achieve 100% hedge"""

    # Current positions (from monitoring)
    current_spot = Decimal('29.99148100')
    current_futures_short = Decimal('20.05')

    # Calculate additional short needed for 100% hedge
    additional_needed = current_spot - current_futures_short

    # Round to correct step size (0.01 for ASTERUSDT futures)
    additional_needed = additional_needed.quantize(Decimal('0.01'))

    print(f"=== Full Hedge Calculation ===")
    print(f"Current Spot ASTER: {current_spot}")
    print(f"Current Futures Short: {current_futures_short}")
    print(f"Additional Short Needed: {additional_needed}")
    print(f"Target Hedge Ratio: 100%")
    print()

    # Create bot instance
    bot = AsterDexFundingBot(capital_usd=Decimal('50'), batch_quote=Decimal('50'))

    # Check futures balance
    print("Checking futures balance...")
    try:
        balance = bot._request(bot.futures_base_url, '/fapi/v2/account', signed=True)
        available = float(balance.get('availableBalance', 0))
        total_wallet = float(balance.get('totalWalletBalance', 0))

        print(f"Available Balance: ${available:.2f}")
        print(f"Total Wallet Balance: ${total_wallet:.2f}")

        # Estimate required margin (assuming ~$2 ASTER price)
        estimated_margin_needed = float(additional_needed) * 2.0
        print(f"Estimated Margin Needed: ${estimated_margin_needed:.2f}")

        if available < estimated_margin_needed:
            print(f"⚠️  Insufficient margin. Available: ${available:.2f}, Need: ~${estimated_margin_needed:.2f}")
            return False

    except Exception as e:
        print(f"Error checking balance: {e}")
        return False

    # Execute the additional short position
    print(f"\nOpening additional {additional_needed} ASTER short position...")

    try:
        # Use the bot's futures short method
        order = bot._place_futures_market_short(additional_needed)

        print(f"✅ Order placed successfully!")
        print(f"Order ID: {order.get('orderId')}")
        print(f"Executed Qty: {order.get('executedQty')}")
        print(f"Average Price: {order.get('avgPrice', 'N/A')}")

        # Verify new hedge ratio
        new_futures_total = current_futures_short + Decimal(str(order.get('executedQty', additional_needed)))
        new_hedge_ratio = new_futures_total / current_spot

        print(f"\n=== New Position Status ===")
        print(f"Spot ASTER: {current_spot}")
        print(f"Futures Short: {new_futures_total}")
        print(f"Hedge Ratio: {new_hedge_ratio:.4f} ({new_hedge_ratio*100:.2f}%)")

        if new_hedge_ratio >= Decimal('0.99'):
            print("🎉 Successfully achieved 99%+ hedge ratio!")
        else:
            print(f"⚠️  Hedge ratio still below 99%: {new_hedge_ratio*100:.2f}%")

        return True

    except Exception as e:
        print(f"❌ Error placing futures order: {e}")
        return False

if __name__ == "__main__":
    achieve_full_hedge()
