#!/usr/bin/env python3
"""
Balance Checker for AsterDex
Check actual available balances before trading
"""

import json
from monitor import AsterDexMonitor
from legacy.funding_bot import configure_logging

def check_actual_balances():
    """Check real account balances"""
    configure_logging("ERROR")  # Reduce noise

    print("🔍 Checking Your Actual AsterDex Balances")
    print("=" * 45)

    try:
        monitor = AsterDexMonitor()

        # Get balances
        spot_balance = monitor.get_spot_balance()
        futures_balance = monitor.get_futures_balance()

        print("💰 SPOT ACCOUNT:")
        print("-" * 20)

        usdt_spot = 0
        aster_spot = 0

        if spot_balance:
            for asset in spot_balance:
                asset_name = asset.get("asset", "")
                free = float(asset.get("free", 0))
                locked = float(asset.get("locked", 0))
                total = free + locked

                if total > 0:
                    print(f"  {asset_name:<8} Free: {free:>10.4f}  Locked: {locked:>10.4f}  Total: {total:>10.4f}")

                    if asset_name == "USDT":
                        usdt_spot = free
                    elif asset_name == "ASTER":
                        aster_spot = total

        print("\n💰 FUTURES ACCOUNT:")
        print("-" * 20)

        usdt_futures = 0
        if futures_balance:
            wallet_balance = float(futures_balance.get("totalWalletBalance", 0))
            available_balance = float(futures_balance.get("availableBalance", 0))
            used_balance = float(futures_balance.get("totalMarginBalance", 0))

            print(f"  Total Wallet:     ${wallet_balance:>10.2f}")
            print(f"  Available:        ${available_balance:>10.2f}")
            print(f"  Used/Margin:      ${used_balance:>10.2f}")

            usdt_futures = available_balance

            # Show assets breakdown if available
            assets = futures_balance.get("assets", [])
            for asset in assets:
                asset_name = asset.get("asset", "")
                wallet_balance = float(asset.get("walletBalance", 0))
                available_balance = float(asset.get("availableBalance", 0))

                if wallet_balance > 0:
                    print(f"  {asset_name:<8} Wallet: ${wallet_balance:>8.2f}  Available: ${available_balance:>8.2f}")

        print("\n📊 TRADING CAPACITY ANALYSIS:")
        print("-" * 35)

        # Calculate trading capacity
        max_spot_buy = usdt_spot  # Can buy this much in USDT

        # Get current price
        from legacy.funding_bot import AsterDexFundingBot
        from decimal import Decimal
        bot = AsterDexFundingBot(capital_usd=Decimal("10"), batch_quote=Decimal("10"))
        current_price = float(bot._fetch_spot_price())

        print(f"  Spot USDT Available:     ${usdt_spot:>8.2f}")
        print(f"  Spot ASTER Holdings:     {aster_spot:>8.4f} ASTER")
        print(f"  Futures USDT Available:  ${usdt_futures:>8.2f}")
        print(f"  Current ASTER Price:     ${current_price:>8.4f}")

        # Calculate maximum safe trade size
        max_spot_order = min(usdt_spot * 0.95, 50)  # 95% of spot balance, max $50
        max_batch_size = min(max_spot_order, 10)    # Conservative batch size

        print(f"\n🎯 RECOMMENDED STRATEGY:")
        print("-" * 25)
        print(f"  Max Safe Spot Order:     ${max_spot_order:>8.2f}")
        print(f"  Recommended Batch Size:  ${max_batch_size:>8.2f}")

        if usdt_spot < 5:
            print(f"  ❌ INSUFFICIENT SPOT BALANCE")
            print(f"     You need at least $5 USDT in spot account")
            print(f"     Currently have: ${usdt_spot:.2f}")
        elif usdt_futures < 5:
            print(f"  ❌ INSUFFICIENT FUTURES BALANCE")
            print(f"     You need at least $5 USDT in futures account")
            print(f"     Currently have: ${usdt_futures:.2f}")
        else:
            # Calculate optimal parameters
            if max_batch_size >= 5:
                num_batches = max(1, int(usdt_spot * 0.8 / max_batch_size))
                total_deployment = num_batches * max_batch_size

                print(f"  ✅ READY TO TRADE")
                print(f"     Suggested: {num_batches} batches of ${max_batch_size:.0f}")
                print(f"     Total deployment: ${total_deployment:.2f}")

                print(f"\n🚀 COMMAND TO RUN:")
                print(f"   uv run python -m legacy.small_capital_strategy --execute \\")
                print(f"     --capital {int(usdt_spot)} --batch-size {int(max_batch_size)}")
            else:
                print(f"  ⚠️  VERY LOW BALANCE")
                print(f"     Consider depositing more USDT")

        return {
            "spot_usdt": usdt_spot,
            "futures_usdt": usdt_futures,
            "max_batch_size": max_batch_size,
            "recommended_capital": min(usdt_spot, usdt_futures) * 0.8
        }

    except Exception as e:
        print(f"❌ Error checking balances: {e}")
        print("\n🔧 TROUBLESHOOTING:")
        print("  1. Check API keys are correct")
        print("  2. Ensure API has read permissions")
        print("  3. Check network connection")
        return None

if __name__ == "__main__":
    result = check_actual_balances()
    if result:
        print(f"\n💾 Balance check saved to balance_check.json")
        with open("balance_check.json", "w") as f:
            json.dump(result, f, indent=2)
