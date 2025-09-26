#!/usr/bin/env python3
"""
Direct Spot Balance Checker using legacy/funding_bot.py authentication
"""

import os
from decimal import Decimal
from legacy.funding_bot import AsterDexFundingBot, configure_logging

def check_spot_balance_direct():
    """Check spot balance using the bot's authentication"""
    print("🔍 Checking Spot Balance (Direct API)")
    print("=" * 40)

    configure_logging("ERROR")  # Reduce noise

    try:
        # Create bot instance just to use its authentication
        bot = AsterDexFundingBot(
            capital_usd=Decimal("10"),
            batch_quote=Decimal("10")
        )

        # Try different spot account endpoints
        endpoints_to_try = [
            "/api/v3/account",      # Standard Binance-style
            "/api/v1/account",      # Alternative
            "/sapi/v1/account",     # Spot API variant
            "/api/v1/userAssets",   # User assets
        ]

        for endpoint in endpoints_to_try:
            try:
                print(f"Trying endpoint: {endpoint}")

                # Use the bot's request method with authentication
                data = bot._request(
                    bot.spot_base_url,
                    endpoint,
                    signed=True
                )

                print(f"✅ SUCCESS with {endpoint}")
                print(f"Response type: {type(data)}")

                # Parse the response
                if isinstance(data, dict):
                    # Look for balance information
                    if "balances" in data:
                        balances = data["balances"]
                        print(f"Found {len(balances)} assets")

                        for balance in balances:
                            asset = balance.get("asset", "")
                            free = float(balance.get("free", 0))
                            locked = float(balance.get("locked", 0))
                            total = free + locked

                            if total > 0:  # Only show non-zero balances
                                print(f"  {asset:<8} Free: {free:>10.4f}  Locked: {locked:>10.4f}")

                        return True

                    elif "assets" in data:
                        assets = data["assets"]
                        print(f"Found {len(assets)} assets")

                        for asset in assets:
                            asset_name = asset.get("asset", "")
                            balance = float(asset.get("balance", 0))

                            if balance > 0:
                                print(f"  {asset_name:<8} Balance: {balance:>10.4f}")

                        return True

                    else:
                        print(f"Unknown response format: {list(data.keys())}")

                elif isinstance(data, list):
                    print(f"Got list with {len(data)} items")
                    if data:
                        print(f"First item: {data[0]}")

            except Exception as e:
                print(f"❌ Failed {endpoint}: {str(e)[:100]}...")
                continue

        print("\n❌ All endpoints failed")
        return False

    except Exception as e:
        print(f"❌ Error creating bot: {e}")
        return False

def check_api_info():
    """Check what API endpoints are available"""
    print("\n🔍 Checking API Information")
    print("=" * 30)

    try:
        bot = AsterDexFundingBot(
            capital_usd=Decimal("10"),
            batch_quote=Decimal("10")
        )

        # Try to get exchange info (this usually works)
        try:
            exchange_info = bot._request(bot.spot_base_url, "/api/v1/exchangeInfo")
            print(f"✅ Exchange info available")
            print(f"   Spot URL: {bot.spot_base_url}")
            print(f"   Symbols available: {len(exchange_info.get('symbols', []))}")

            # Show API key (first few chars)
            api_key = bot._api_key
            print(f"   API Key: {api_key[:8]}...{api_key[-4:]}")

        except Exception as e:
            print(f"❌ Exchange info failed: {e}")

        # Try to get server time
        try:
            time_data = bot._request(bot.spot_base_url, "/api/v1/time")
            print(f"✅ Server time: {time_data}")
        except Exception as e:
            print(f"❌ Server time failed: {e}")

    except Exception as e:
        print(f"❌ API info check failed: {e}")

if __name__ == "__main__":
    print("🚀 AsterDex Spot Balance Checker")
    print("Using legacy/funding_bot.py authentication")
    print("=" * 50)

    # First check API connectivity
    check_api_info()

    # Then try to get balance
    success = check_spot_balance_direct()

    if not success:
        print("\n💡 Troubleshooting Tips:")
        print("1. Check if API keys have spot trading permissions")
        print("2. Verify API keys are correct in environment or defaults")
        print("3. Check if you have any assets in spot account")
        print("4. Try logging into AsterDex web interface to verify account")

        # Show current API keys being used (masked)
        try:
            api_key = os.environ.get("ASTERDEX_API_KEY") or ""
            print(f"\n🔑 Using API Key: {api_key[:8]}...{api_key[-4:]}")
        except:
            pass
