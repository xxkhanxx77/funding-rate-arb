#!/usr/bin/env python3
"""
Funding Rate APY Calculator for AsterDex
Calculates APY based on current funding rates and historical data
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from decimal import Decimal
from dexes.factory import DexFactory

logger = logging.getLogger(__name__)


class FundingAPYCalculator:
    """Calculate APY from funding rates"""

    def __init__(self, dex_name: str = "asterdex"):
        self.dex_name = dex_name
        self.client = DexFactory.create_client(dex_name)

    def get_current_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """Get current funding rate for a symbol"""
        try:
            # Use the mark price endpoint which includes funding rate
            if symbol.upper() == "ASTER":
                symbol = "ASTERUSDT"

            data = self.client._request(
                self.client.futures_base_url,
                "/fapi/v1/premiumIndex",
                params={"symbol": symbol}
            )

            return {
                "symbol": data.get("symbol"),
                "mark_price": float(data.get("markPrice", 0)),
                "index_price": float(data.get("indexPrice", 0)),
                "last_funding_rate": float(data.get("lastFundingRate", 0)),
                "next_funding_time": data.get("nextFundingTime"),
                "interest_rate": float(data.get("interestRate", 0)),
                "time": data.get("time")
            }

        except Exception as e:
            logger.error(f"Error getting current funding rate for {symbol}: {e}")
            return {}

    def get_funding_rate_history(self, symbol: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get funding rate history using income API"""
        try:
            if symbol.upper() == "ASTER":
                symbol = "ASTERUSDT"

            # Get funding payments to calculate historical rates
            start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

            params = {
                "symbol": symbol,
                "incomeType": "FUNDING_FEE",
                "startTime": start_time,
                "limit": 1000
            }

            funding_history = self.client._request(
                self.client.futures_base_url,
                "/fapi/v1/income",
                params=params,
                signed=True
            )

            return funding_history

        except Exception as e:
            logger.error(f"Error getting funding history for {symbol}: {e}")
            return []

    def calculate_apy_from_current_rate(self, symbol: str) -> Dict[str, Any]:
        """Calculate APY from current funding rate"""
        try:
            rate_info = self.get_current_funding_rate(symbol)

            if not rate_info:
                return {"error": "Could not get funding rate"}

            # Funding happens every 8 hours (3 times per day)
            current_rate = rate_info["last_funding_rate"]

            # Calculate APY
            # APY = (1 + daily_rate)^365 - 1
            # Daily rate = funding_rate * 3 (3 times per day)
            daily_rate = current_rate * 3
            apy = (1 + daily_rate) ** 365 - 1

            # Also calculate simple annualized rate
            simple_annual = daily_rate * 365

            return {
                "symbol": rate_info["symbol"],
                "current_funding_rate": current_rate,
                "current_rate_percent": current_rate * 100,
                "daily_rate": daily_rate,
                "daily_rate_percent": daily_rate * 100,
                "apy": apy,
                "apy_percent": apy * 100,
                "simple_annual_percent": simple_annual * 100,
                "mark_price": rate_info["mark_price"],
                "next_funding_time": rate_info["next_funding_time"],
                "calculation_time": datetime.now().isoformat(),
                "funding_frequency": "Every 8 hours (3x daily)"
            }

        except Exception as e:
            logger.error(f"Error calculating APY for {symbol}: {e}")
            return {"error": str(e)}

    def calculate_apy_from_historical_performance(self, symbol: str, days: int = 30) -> Dict[str, Any]:
        """Calculate realized APY from actual funding payments"""
        try:
            if symbol.upper() == "ASTER":
                symbol = "ASTERUSDT"

            # Get actual funding payments
            funding_payments = self.get_funding_rate_history(symbol, days)

            if not funding_payments:
                return {"error": "No funding payment history available"}

            # Get current position size to calculate rates
            positions = self.client.get_futures_positions()
            position_size = 0

            for pos in positions:
                if pos.get("symbol") == symbol:
                    position_size = abs(float(pos.get("positionAmt", 0)))
                    break

            if position_size == 0:
                return {"error": "No position found to calculate realized rates"}

            # Calculate total income and average position value
            total_income = sum(float(p.get("income", 0)) for p in funding_payments)

            # Estimate average position value (using current mark price)
            rate_info = self.get_current_funding_rate(symbol)
            mark_price = rate_info.get("mark_price", 0)
            position_value = position_size * mark_price

            # Calculate realized rates
            period_return = total_income / position_value if position_value > 0 else 0
            daily_return = period_return / days

            # Calculate APY from realized performance
            realized_apy = (1 + daily_return) ** 365 - 1 if daily_return > -1 else -1

            return {
                "symbol": symbol,
                "period_days": days,
                "total_funding_income": total_income,
                "position_size": position_size,
                "position_value": position_value,
                "period_return": period_return,
                "period_return_percent": period_return * 100,
                "daily_return": daily_return,
                "daily_return_percent": daily_return * 100,
                "realized_apy": realized_apy,
                "realized_apy_percent": realized_apy * 100,
                "payment_count": len(funding_payments),
                "calculation_time": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error calculating realized APY for {symbol}: {e}")
            return {"error": str(e)}

    def get_comprehensive_apy_analysis(self, symbol: str) -> Dict[str, Any]:
        """Get comprehensive APY analysis combining current rates and historical performance"""
        try:
            current_apy = self.calculate_apy_from_current_rate(symbol)
            historical_apy = self.calculate_apy_from_historical_performance(symbol, 30)
            historical_7d = self.calculate_apy_from_historical_performance(symbol, 7)

            return {
                "symbol": symbol.upper(),
                "analysis_time": datetime.now().isoformat(),
                "current_rate_apy": current_apy,
                "realized_apy_30d": historical_apy,
                "realized_apy_7d": historical_7d,
                "summary": {
                    "current_apy_estimate": current_apy.get("apy_percent", 0),
                    "realized_apy_30d": historical_apy.get("realized_apy_percent", 0),
                    "realized_apy_7d": historical_7d.get("realized_apy_percent", 0),
                    "funding_frequency": "Every 8 hours (3x daily)",
                    "strategy_status": "Active" if historical_apy.get("position_size", 0) > 0 else "Inactive"
                }
            }

        except Exception as e:
            logger.error(f"Error in comprehensive APY analysis: {e}")
            return {"error": str(e)}


def main():
    """Test the APY calculator"""
    calculator = FundingAPYCalculator()

    # Get symbol from config or default to ASTER
    symbol = os.getenv("FUNDING_SPOT_SYMBOL", "ASTER").replace("USDT", "")

    print(f"=== Funding APY Analysis for {symbol} ===")
    print()

    # Current rate APY
    print("Current Funding Rate APY:")
    current_apy = calculator.calculate_apy_from_current_rate(symbol)
    if "error" not in current_apy:
        print(f"  Current Rate: {current_apy['current_rate_percent']:.4f}%")
        print(f"  Daily Rate: {current_apy['daily_rate_percent']:.4f}%")
        print(f"  Estimated APY: {current_apy['apy_percent']:.2f}%")
        print(f"  Simple Annual: {current_apy['simple_annual_percent']:.2f}%")
    else:
        print(f"  Error: {current_apy['error']}")

    print()

    # Realized APY (30 days)
    print("Realized APY (30 days):")
    realized_apy = calculator.calculate_apy_from_historical_performance(symbol, 30)
    if "error" not in realized_apy:
        print(f"  Total Income: ${realized_apy['total_funding_income']:.6f}")
        print(f"  Period Return: {realized_apy['period_return_percent']:.4f}%")
        print(f"  Daily Return: {realized_apy['daily_return_percent']:.4f}%")
        print(f"  Realized APY: {realized_apy['realized_apy_percent']:.2f}%")
        print(f"  Funding Payments: {realized_apy['payment_count']}")
    else:
        print(f"  Error: {realized_apy['error']}")

    print()

    # Comprehensive analysis
    print("Summary:")
    analysis = calculator.get_comprehensive_apy_analysis(symbol)
    if "error" not in analysis:
        summary = analysis["summary"]
        print(f"  Current APY Estimate: {summary['current_apy_estimate']:.2f}%")
        print(f"  Realized APY (30d): {summary['realized_apy_30d']:.2f}%")
        print(f"  Realized APY (7d): {summary['realized_apy_7d']:.2f}%")
        print(f"  Strategy: {summary['strategy_status']}")
    else:
        print(f"  Error: {analysis['error']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
