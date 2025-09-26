#!/usr/bin/env python3
"""
Convert USDC to USDT on AsterDex spot market
Then run the funding strategy with USDT
"""

import argparse
from decimal import Decimal
from legacy.funding_bot import AsterDexFundingBot, configure_logging
import json

def check_usdc_to_usdt_rate():
    """Check the USDC/USDT exchange rate"""
    print("💱 Checking USDC/USDT Exchange Rate")
    print("=" * 35)

    try:
        bot = AsterDexFundingBot(capital_usd=Decimal("10"), batch_quote=Decimal("10"))

        # Get USDCUSDT price
        price_data = bot._request(
            bot.spot_base_url,
            "/api/v1/ticker/price",
            params={"symbol": "USDCUSDT"}
        )

        rate = float(price_data.get("price", 0))
        print(f"📊 USDCUSDT Rate: {rate:.6f}")
        print(f"💰 100 USDC = ~{100 * rate:.2f} USDT")

        return rate

    except Exception as e:
        print(f"❌ Error checking rate: {e}")
        return None

def convert_usdc_to_usdt(amount_usdc=90):
    """Convert USDC to USDT"""
    print(f"\n💱 Converting {amount_usdc} USDC to USDT")
    print("=" * 35)

    try:
        # Create bot instance for API access
        bot = AsterDexFundingBot(capital_usd=Decimal("10"), batch_quote=Decimal("10"))

        print(f"🔄 Selling {amount_usdc} USDC for USDT...")

        # Place market sell order: sell USDC, receive USDT
        payload = {
            "symbol": "USDCUSDT",
            "side": "SELL",  # Sell USDC
            "type": "MARKET",
            "quantity": str(amount_usdc),  # Amount of USDC to sell
            "newOrderRespType": "FULL",
        }

        result = bot._request(
            bot.spot_base_url,
            "/api/v1/order",
            method="POST",
            params=payload,
            signed=True
        )

        executed_qty = float(result.get("executedQty", 0))
        quote_received = 0

        # Calculate USDT received from fills
        for fill in result.get("fills", []):
            quote_received += float(fill.get("qty", 0)) * float(fill.get("price", 0))

        print(f"✅ Conversion completed!")
        print(f"   USDC sold: {executed_qty:.2f}")
        print(f"   USDT received: {quote_received:.2f}")

        return quote_received

    except Exception as e:
        print(f"❌ Conversion failed: {e}")

        if "Balance is insufficient" in str(e):
            print(f"💡 You might not have enough USDC in spot account")
            print(f"   Check your balance and try a smaller amount")

        return None

def run_funding_strategy_after_conversion(usdt_amount):
    """Run the funding strategy with converted USDT"""
    print(f"\n🚀 Running Funding Strategy with {usdt_amount:.2f} USDT")
    print("=" * 45)

    # Use 80% of converted USDT for safety
    capital = int(usdt_amount * 0.8)
    batch_size = min(20, capital // 4)  # 4 batches

    print(f"Capital to deploy: ${capital}")
    print(f"Batch size: ${batch_size}")

    if capital < 10:
        print("❌ Insufficient capital after conversion")
        return None

    try:
        from legacy.small_capital_strategy import execute_small_capital_strategy, create_small_capital_config

        config = create_small_capital_config(capital, batch_size)
        result = execute_small_capital_strategy(config, confirm=False)

        return result

    except Exception as e:
        print(f"❌ Funding strategy failed: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Convert USDC to USDT and run funding strategy")
    parser.add_argument("--check-rate", action="store_true", help="Check USDC/USDT rate")
    parser.add_argument("--convert", type=float, default=90, help="Amount of USDC to convert")
    parser.add_argument("--full-strategy", action="store_true", help="Convert and run funding strategy")

    args = parser.parse_args()
    configure_logging("INFO")

    if args.check_rate:
        rate = check_usdc_to_usdt_rate()
        if rate:
            print(f"\n💡 With current rate, you can get ~${100 * rate:.2f} USDT from 100 USDC")

    elif args.full_strategy:
        print("🔄 Full Strategy: Convert USDC → Run Funding Bot")
        print("=" * 50)

        # Step 1: Check rate
        rate = check_usdc_to_usdt_rate()
        if not rate:
            print("❌ Cannot check exchange rate")
            return

        # Step 2: Convert USDC to USDT
        usdt_received = convert_usdc_to_usdt(args.convert)
        if not usdt_received:
            print("❌ USDC conversion failed")
            return

        # Step 3: Run funding strategy
        result = run_funding_strategy_after_conversion(usdt_received)
        if result:
            print("✅ Full strategy completed successfully!")
            with open("full_strategy_result.json", "w") as f:
                json.dump(result, f, indent=2)
        else:
            print("❌ Funding strategy failed")

    else:
        # Just convert
        usdt_received = convert_usdc_to_usdt(args.convert)
        if usdt_received:
            print(f"\n🎯 Next step: Run funding strategy with {usdt_received:.2f} USDT")
            print(f"python -m legacy.small_capital_strategy --execute --capital {int(usdt_received * 0.8)} --batch-size 20")

    print(f"\n💡 Usage examples:")
    print(f"python {parser.prog} --check-rate")
    print(f"python {parser.prog} --convert 90")
    print(f"python {parser.prog} --full-strategy")

if __name__ == "__main__":
    main()
