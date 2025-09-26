#!/usr/bin/env python3
"""
Simple USDC to USDT converter
"""

from decimal import Decimal
from legacy.funding_bot import AsterDexFundingBot, configure_logging

def convert_usdc_to_usdt_simple(amount_usdc=10):
    """Convert USDC to USDT using market order"""
    print(f"💱 Converting {amount_usdc} USDC to USDT")
    print("=" * 30)

    configure_logging("INFO")

    try:
        # Create bot instance for API access
        bot = AsterDexFundingBot(capital_usd=Decimal("10"), batch_quote=Decimal("10"))

        # Check current rate
        price_data = bot._request(
            bot.spot_base_url,
            "/api/v1/ticker/price",
            params={"symbol": "USDCUSDT"}
        )

        rate = float(price_data.get("price", 1.0))
        print(f"📊 Current USDCUSDT rate: {rate}")
        print(f"💰 {amount_usdc} USDC → ~{amount_usdc * rate:.2f} USDT")

        # Place market sell order to convert USDC to USDT
        print(f"\n🔄 Placing conversion order...")

        payload = {
            "symbol": "USDCUSDT",
            "side": "SELL",  # Sell USDC, receive USDT
            "type": "MARKET",
            "quantity": str(amount_usdc),
            "newOrderRespType": "FULL",
        }

        result = bot._request(
            bot.spot_base_url,
            "/api/v1/order",
            method="POST",
            params=payload,
            signed=True
        )

        print(f"✅ Conversion order placed!")
        print(f"Order ID: {result.get('orderId')}")
        print(f"Status: {result.get('status')}")

        # Parse execution details
        executed_qty = float(result.get('executedQty', 0))

        # Calculate USDT received
        usdt_received = 0
        fills = result.get('fills', [])

        if fills:
            print(f"\n📊 Execution Details:")
            for i, fill in enumerate(fills, 1):
                qty = float(fill.get('qty', 0))
                price = float(fill.get('price', 0))
                usdt_amount = qty * price
                usdt_received += usdt_amount

                print(f"  Fill {i}: {qty:.4f} USDC @ {price:.6f} = {usdt_amount:.4f} USDT")

        print(f"\n✅ Conversion Summary:")
        print(f"   USDC Sold: {executed_qty:.4f}")
        print(f"   USDT Received: {usdt_received:.4f}")

        # Check new balance
        print(f"\n🔍 Checking updated balance...")
        account_data = bot._request(bot.spot_base_url, "/api/v1/account", signed=True)

        for balance in account_data.get("balances", []):
            asset = balance.get("asset", "")
            free = float(balance.get("free", 0))

            if asset in ["USDT", "USDC"] and free > 0:
                print(f"   {asset}: {free:.4f}")

        return usdt_received

    except Exception as e:
        print(f"❌ Conversion failed: {e}")

        if "insufficient" in str(e).lower():
            print("💡 Make sure you have 10 USDC available in spot account")
        elif "Invalid symbol" in str(e):
            print("💡 USDCUSDT pair might not be available")

        return None

if __name__ == "__main__":
    print("🚀 USDC to USDT Converter")
    print("=" * 25)

    result = convert_usdc_to_usdt_simple(10)

    if result:
        print(f"\n🎉 Success! You now have ~{result:.2f} more USDT")
        print(f"💡 Total USDT available: ~{89.91 + result:.2f}")
        print(f"\n🎯 You can now run a larger funding strategy:")
        print(f"uv run python legacy/funding_bot.py --capital 60 --batch-quote 20")
    else:
        print(f"\n❌ Conversion failed. Check the error above.")
