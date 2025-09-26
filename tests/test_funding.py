#!/usr/bin/env python3
from legacy.funding_bot import AsterDexFundingBot
from decimal import Decimal
from datetime import datetime, timedelta

def test_funding_income():
    """Test the /fapi/v1/income endpoint for FUNDING_FEE"""

    bot = AsterDexFundingBot(capital_usd=Decimal('10'), batch_quote=Decimal('10'))

    print("=== Testing Funding Fee Income API ===\n")

    # Test different time periods
    periods = [
        ("1 day", 1),
        ("7 days", 7),
        ("30 days", 30)
    ]

    for period_name, days in periods:
        try:
            start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

            params = {
                "incomeType": "FUNDING_FEE",
                "startTime": start_time,
                "limit": 1000
            }

            print(f"--- {period_name} ---")

            income_data = bot._request(
                bot.futures_base_url,
                "/fapi/v1/income",
                params=params,
                signed=True
            )

            if income_data:
                total_funding = sum(float(item.get("income", 0)) for item in income_data)
                aster_funding = [item for item in income_data if item.get("symbol") == "ASTERUSDT"]
                aster_total = sum(float(item.get("income", 0)) for item in aster_funding)

                print(f"Total funding entries: {len(income_data)}")
                print(f"ASTERUSDT funding entries: {len(aster_funding)}")
                print(f"Total funding income: ${total_funding:.6f}")
                print(f"ASTERUSDT funding income: ${aster_total:.6f}")

                if aster_funding:
                    print("Recent ASTERUSDT funding payments:")
                    for payment in aster_funding[:5]:  # Show last 5
                        time_str = datetime.fromtimestamp(payment.get("time", 0) / 1000).strftime("%Y-%m-%d %H:%M:%S")
                        print(f"  {time_str}: ${payment.get('income')} (tranId: {payment.get('tranId')})")
                print()
            else:
                print("No funding fee data found")
                print()

        except Exception as e:
            print(f"Error getting {period_name} funding data: {e}")
            print()

    # Test getting all income types for comparison
    try:
        print("--- All Income Types (Last 7 days) ---")
        start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        all_income = bot._request(
            bot.futures_base_url,
            "/fapi/v1/income",
            params={
                "startTime": start_time,
                "limit": 100
            },
            signed=True
        )

        if all_income:
            income_types = {}
            for item in all_income:
                income_type = item.get("incomeType")
                if income_type not in income_types:
                    income_types[income_type] = {"count": 0, "total": 0}
                income_types[income_type]["count"] += 1
                income_types[income_type]["total"] += float(item.get("income", 0))

            print("Income type breakdown:")
            for inc_type, data in income_types.items():
                print(f"  {inc_type}: {data['count']} entries, ${data['total']:.6f}")

    except Exception as e:
        print(f"Error getting all income types: {e}")

if __name__ == "__main__":
    test_funding_income()
