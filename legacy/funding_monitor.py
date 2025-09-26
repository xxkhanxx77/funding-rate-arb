#!/usr/bin/env python3
"""
Dedicated Funding Fee Bot Portfolio Monitor
Real-time tracking of spot and futures positions
"""

import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from monitor import AsterDexMonitor
from legacy.funding_bot import configure_logging
import argparse

class FundingBotMonitor:
    def __init__(self):
        self.monitor = AsterDexMonitor()

    def get_funding_position_status(self):
        """Get comprehensive status of funding bot positions"""
        try:
            # Get current balances and positions
            spot_balance = self.monitor.get_spot_balance()
            futures_positions = self.monitor.get_futures_positions()
            futures_balance = self.monitor.get_futures_balance()
            funding_payments = self.monitor.get_funding_payments(days=1)

            # Parse spot holdings
            spot_holdings = {}
            for asset in spot_balance:
                symbol = asset.get("asset", "")
                free = float(asset.get("free", 0))
                locked = float(asset.get("locked", 0))
                if free > 0 or locked > 0:
                    spot_holdings[symbol] = {"free": free, "locked": locked, "total": free + locked}

            # Parse futures positions
            active_positions = []
            for pos in futures_positions:
                symbol = pos.get("symbol", "")
                size = float(pos.get("positionAmt", 0))
                if abs(size) > 0.001:  # Only positions with meaningful size
                    active_positions.append({
                        "symbol": symbol,
                        "size": size,
                        "side": "LONG" if size > 0 else "SHORT",
                        "entry_price": float(pos.get("entryPrice", 0)),
                        "mark_price": float(pos.get("markPrice", 0)),
                        "pnl": float(pos.get("unRealizedProfit", 0)),
                        "notional": abs(size) * float(pos.get("markPrice", 0))
                    })

            return {
                "timestamp": datetime.now().isoformat(),
                "spot_holdings": spot_holdings,
                "futures_positions": active_positions,
                "futures_balance": {
                    "total_wallet": float(futures_balance.get("totalWalletBalance", 0)),
                    "available": float(futures_balance.get("availableBalance", 0)),
                    "margin_used": float(futures_balance.get("totalMarginBalance", 0))
                },
                "recent_funding": funding_payments[-10:] if funding_payments else []
            }

        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now().isoformat()}

    def analyze_funding_strategy(self):
        """Analyze the current funding strategy performance"""
        status = self.get_funding_position_status()

        if "error" in status:
            return status

        analysis = {
            "timestamp": status["timestamp"],
            "strategy_health": "UNKNOWN",
            "position_matching": {},
            "funding_performance": {},
            "recommendations": []
        }

        # Analyze position matching
        spot_holdings = status["spot_holdings"]
        futures_positions = status["futures_positions"]

        # Look for ASTER positions (our main trading pair)
        aster_spot = spot_holdings.get("ASTER", {}).get("total", 0)
        aster_futures = None

        for pos in futures_positions:
            if pos["symbol"] == "ASTERUSDT":
                aster_futures = pos
                break

        if aster_spot > 0 and aster_futures:
            futures_size = abs(aster_futures["size"])
            hedge_ratio = futures_size / aster_spot if aster_spot > 0 else 0

            analysis["position_matching"] = {
                "spot_aster": aster_spot,
                "futures_aster": futures_size,
                "futures_side": aster_futures["side"],
                "hedge_ratio": hedge_ratio,
                "is_properly_hedged": 0.95 <= hedge_ratio <= 1.05,
                "hedge_efficiency": min(hedge_ratio, 1.0)
            }

            # Strategy health assessment
            if aster_futures["side"] == "SHORT" and 0.95 <= hedge_ratio <= 1.05:
                analysis["strategy_health"] = "HEALTHY"
            elif hedge_ratio < 0.95:
                analysis["strategy_health"] = "UNDER_HEDGED"
                analysis["recommendations"].append("Consider adding more futures short position")
            elif hedge_ratio > 1.05:
                analysis["strategy_health"] = "OVER_HEDGED"
                analysis["recommendations"].append("Consider reducing futures short position")
            else:
                analysis["strategy_health"] = "MISALIGNED"
                analysis["recommendations"].append("Check position directions")

        # Analyze funding performance
        recent_funding = status["recent_funding"]
        if recent_funding:
            total_funding_today = sum(float(p.get("income", 0)) for p in recent_funding)
            analysis["funding_performance"] = {
                "payments_today": len(recent_funding),
                "total_income_today": total_funding_today,
                "average_payment": total_funding_today / len(recent_funding) if recent_funding else 0
            }

        # Calculate portfolio value
        portfolio_value = 0
        if aster_futures:
            portfolio_value = aster_spot * aster_futures.get("mark_price", 0)

        analysis["portfolio_value"] = portfolio_value
        analysis["daily_funding_rate"] = self._get_current_funding_rate("ASTERUSDT")

        return analysis

    def _get_current_funding_rate(self, symbol):
        """Get current funding rate for a symbol"""
        try:
            funding_info = self.monitor.get_funding_info([symbol])
            if funding_info:
                rate = funding_info[0].get("premium_index", {}).get("lastFundingRate", "0")
                return float(rate) * 100  # Convert to percentage
        except:
            pass
        return 0.0

    def display_funding_dashboard(self):
        """Display a comprehensive funding dashboard"""
        print("🚀 FUNDING BOT PORTFOLIO MONITOR")
        print("=" * 50)
        print(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Get analysis
        analysis = self.analyze_funding_strategy()

        if "error" in analysis:
            print(f"❌ Error: {analysis['error']}")
            return

        # Display strategy health
        health = analysis.get("strategy_health", "UNKNOWN")
        health_icon = {
            "HEALTHY": "✅",
            "UNDER_HEDGED": "⚠️ ",
            "OVER_HEDGED": "⚠️ ",
            "MISALIGNED": "❌",
            "UNKNOWN": "❓"
        }.get(health, "❓")

        print(f"\n{health_icon} Strategy Health: {health}")

        # Display position matching
        matching = analysis.get("position_matching", {})
        if matching:
            print(f"\n📊 POSITION ANALYSIS")
            print("-" * 25)
            print(f"Spot ASTER:      {matching.get('spot_aster', 0):>10.4f} tokens")
            print(f"Futures ASTER:   {matching.get('futures_aster', 0):>10.4f} tokens ({matching.get('futures_side', 'N/A')})")
            print(f"Hedge Ratio:     {matching.get('hedge_ratio', 0):>10.2%}")
            print(f"Hedge Efficiency: {matching.get('hedge_efficiency', 0):>9.1%}")

        # Display funding performance
        funding = analysis.get("funding_performance", {})
        if funding:
            print(f"\n💰 FUNDING PERFORMANCE (Today)")
            print("-" * 30)
            print(f"Payments Received: {funding.get('payments_today', 0):>8d}")
            print(f"Total Income:     ${funding.get('total_income_today', 0):>8.4f}")
            print(f"Avg per Payment:  ${funding.get('average_payment', 0):>8.4f}")

        # Display current rates
        current_rate = analysis.get("daily_funding_rate", 0)
        portfolio_value = analysis.get("portfolio_value", 0)

        print(f"\n📈 CURRENT METRICS")
        print("-" * 20)
        print(f"Portfolio Value:  ${portfolio_value:>10.2f}")
        print(f"Funding Rate:     {current_rate:>9.4f}%")

        if current_rate > 0 and portfolio_value > 0:
            daily_estimate = portfolio_value * (current_rate / 100) * 3  # 3 funding cycles per day
            monthly_estimate = daily_estimate * 30
            print(f"Est. Daily:       ${daily_estimate:>10.4f}")
            print(f"Est. Monthly:     ${monthly_estimate:>10.2f}")

        # Display recommendations
        recommendations = analysis.get("recommendations", [])
        if recommendations:
            print(f"\n💡 RECOMMENDATIONS")
            print("-" * 20)
            for i, rec in enumerate(recommendations, 1):
                print(f"{i}. {rec}")

    def get_api_data(self):
        """Return JSON data for API consumption"""
        status = self.get_funding_position_status()
        analysis = self.analyze_funding_strategy()

        return {
            "status": status,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }

def main():
    parser = argparse.ArgumentParser(description="Funding Bot Portfolio Monitor")
    parser.add_argument("--dashboard", action="store_true", help="Show dashboard")
    parser.add_argument("--json", action="store_true", help="Output JSON data")
    parser.add_argument("--watch", action="store_true", help="Watch mode (refresh every 30s)")
    parser.add_argument("--save", help="Save data to file")

    args = parser.parse_args()
    configure_logging("ERROR")  # Reduce noise

    monitor = FundingBotMonitor()

    if args.watch:
        print("👀 Watch Mode - Press Ctrl+C to exit")
        print("Refreshing every 30 seconds...")

        try:
            while True:
                print("\n" + "="*60)
                monitor.display_funding_dashboard()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped")

    elif args.json:
        data = monitor.get_api_data()
        print(json.dumps(data, indent=2))

        if args.save:
            with open(args.save, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"💾 Data saved to {args.save}")

    elif args.dashboard:
        monitor.display_funding_dashboard()

        if args.save:
            data = monitor.get_api_data()
            with open(args.save, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"\n💾 Data saved to {args.save}")

    else:
        parser.print_help()
        print(f"\n💡 Quick start:")
        print(f"  python {parser.prog} --dashboard")
        print(f"  python {parser.prog} --json")
        print(f"  python {parser.prog} --watch")

if __name__ == "__main__":
    main()
