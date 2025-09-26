#!/usr/bin/env python3
from legacy.funding_bot import AsterDexFundingBot
from decimal import Decimal
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_and_set_leverage():
    """Check current leverage and set to 1x for minimum risk"""

    # Create bot instance
    bot = AsterDexFundingBot(capital_usd=Decimal('10'), batch_quote=Decimal('10'))

    symbol = "ASTERUSDT"
    target_leverage = 1

    print(f"=== Leverage Management for {symbol} ===")

    # Check current leverage
    try:
        # Get current position info which includes leverage
        positions = bot._request(bot.futures_base_url, '/fapi/v2/positionRisk', signed=True)

        aster_position = None
        for pos in positions:
            if pos.get('symbol') == symbol:
                aster_position = pos
                break

        if aster_position:
            current_leverage = float(aster_position.get('leverage', 0))
            position_amt = float(aster_position.get('positionAmt', 0))
            entry_price = float(aster_position.get('entryPrice', 0))
            mark_price = float(aster_position.get('markPrice', 0))
            notional = abs(position_amt) * mark_price
            margin_used = notional / current_leverage if current_leverage > 0 else 0

            print(f"Current Position:")
            print(f"  Symbol: {symbol}")
            print(f"  Position Size: {position_amt} ASTER")
            print(f"  Current Leverage: {current_leverage}x")
            print(f"  Entry Price: ${entry_price:.6f}")
            print(f"  Mark Price: ${mark_price:.6f}")
            print(f"  Notional Value: ${notional:.2f}")
            print(f"  Margin Used: ${margin_used:.2f}")
            print()

            if current_leverage == target_leverage:
                print(f"✅ Leverage already set to {target_leverage}x (minimum risk)")
                return True
            elif current_leverage > target_leverage:
                print(f"⚠️  Current leverage ({current_leverage}x) is higher than target ({target_leverage}x)")
                print(f"   Setting to {target_leverage}x will increase margin requirement")

                # Calculate new margin requirement
                new_margin_needed = notional / target_leverage
                additional_margin = new_margin_needed - margin_used

                print(f"   New margin needed: ${new_margin_needed:.2f}")
                print(f"   Additional margin required: ${additional_margin:.2f}")

                # Check available balance
                balance = bot._request(bot.futures_base_url, '/fapi/v2/account', signed=True)
                available = float(balance.get('availableBalance', 0))

                print(f"   Available balance: ${available:.2f}")

                if available < additional_margin:
                    print(f"❌ Insufficient margin! Need ${additional_margin:.2f}, have ${available:.2f}")
                    return False

            else:
                print(f"✅ Current leverage ({current_leverage}x) is already lower than target")

    except Exception as e:
        print(f"Error checking current position: {e}")
        return False

    # Set leverage to 1x
    print(f"Setting leverage to {target_leverage}x...")

    try:
        # Use the leverage endpoint
        result = bot._request(
            bot.futures_base_url,
            '/fapi/v1/leverage',
            method='POST',
            params={
                'symbol': symbol,
                'leverage': target_leverage
            },
            signed=True
        )

        print(f"✅ Leverage set successfully!")
        print(f"   Symbol: {result.get('symbol')}")
        print(f"   Leverage: {result.get('leverage')}x")
        print(f"   Max Notional: {result.get('maxNotionalValue')}")

        # Check new position after leverage change
        print(f"\nVerifying new position...")
        positions = bot._request(bot.futures_base_url, '/fapi/v2/positionRisk', signed=True)

        for pos in positions:
            if pos.get('symbol') == symbol:
                new_leverage = float(pos.get('leverage', 0))
                position_amt = float(pos.get('positionAmt', 0))
                mark_price = float(pos.get('markPrice', 0))
                notional = abs(position_amt) * mark_price
                new_margin = notional / new_leverage if new_leverage > 0 else 0

                print(f"✅ New Position Status:")
                print(f"   Leverage: {new_leverage}x")
                print(f"   Position Size: {position_amt} ASTER")
                print(f"   Notional: ${notional:.2f}")
                print(f"   Margin Used: ${new_margin:.2f}")
                print(f"   Risk Level: MINIMUM (1x leverage)")
                break

        return True

    except Exception as e:
        print(f"❌ Error setting leverage: {e}")
        return False

if __name__ == "__main__":
    success = check_and_set_leverage()
    if success:
        print(f"\n🎉 Leverage successfully set to 1x for minimum risk!")
    else:
        print(f"\n❌ Failed to set leverage. Check error messages above.")
