#!/usr/bin/env python3
"""
AsterDex Monitor Implementation
Refactored from the original monitor.py
"""

import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from ..base.dex_interface import BaseMonitor
from .client import AsterDexClient

logger = logging.getLogger(__name__)


class AsterDexMonitor(BaseMonitor):
    """AsterDex portfolio monitoring implementation"""

    def __init__(self, dex: AsterDexClient):
        super().__init__(dex)

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get comprehensive portfolio summary"""
        try:
            spot_balance = self.dex.get_spot_balance()
            futures_balance = self.dex.get_futures_balance()
            futures_positions = self.dex.get_futures_positions()

            # Calculate total portfolio value
            total_spot_usd = sum(
                float(asset.get("free", 0)) * self._get_price_usd(asset["asset"])
                for asset in spot_balance
            )

            total_futures_usd = float(futures_balance.get("totalWalletBalance", 0))

            return {
                "dex": self.dex.get_name(),
                "timestamp": datetime.now().isoformat(),
                "spot": {
                    "balance": spot_balance,
                    "total_usd": total_spot_usd
                },
                "futures": {
                    "balance": futures_balance,
                    "positions": futures_positions,
                    "total_usd": total_futures_usd
                },
                "portfolio": {
                    "total_usd": total_spot_usd + total_futures_usd,
                    "spot_ratio": total_spot_usd / (total_spot_usd + total_futures_usd) if (total_spot_usd + total_futures_usd) > 0 else 0,
                    "futures_ratio": total_futures_usd / (total_spot_usd + total_futures_usd) if (total_spot_usd + total_futures_usd) > 0 else 0
                }
            }
        except Exception as e:
            logger.error(f"Error getting portfolio summary: {e}")
            return {
                "dex": self.dex.get_name(),
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "spot": {"balance": [], "total_usd": 0},
                "futures": {"balance": {}, "positions": [], "total_usd": 0},
                "portfolio": {"total_usd": 0, "spot_ratio": 0, "futures_ratio": 0}
            }

    def get_hedging_efficiency(self) -> Dict[str, Any]:
        """Calculate hedging efficiency between spot and futures"""
        try:
            spot_balance = self.dex.get_spot_balance()
            futures_positions = self.dex.get_futures_positions()

            # Find matching spot/futures pairs
            hedged_pairs = []

            for spot_asset in spot_balance:
                asset = spot_asset["asset"]
                if asset == "USDT":
                    continue

                spot_qty = float(spot_asset.get("free", 0))
                futures_symbol = f"{asset}USDT"

                # Find matching futures position
                futures_pos = next(
                    (p for p in futures_positions if p.get("symbol") == futures_symbol),
                    None
                )

                if futures_pos:
                    futures_qty = abs(float(futures_pos.get("positionAmt", 0)))
                    hedge_ratio = futures_qty / spot_qty if spot_qty > 0 else 0

                    hedged_pairs.append({
                        "symbol": futures_symbol,
                        "spot_qty": spot_qty,
                        "futures_qty": futures_qty,
                        "hedge_ratio": hedge_ratio,
                        "hedge_efficiency": min(hedge_ratio, 1.0),  # Capped at 100%
                        "is_over_hedged": hedge_ratio > 1.05,
                        "is_under_hedged": hedge_ratio < 0.95
                    })

            avg_efficiency = sum(p["hedge_efficiency"] for p in hedged_pairs) / len(hedged_pairs) if hedged_pairs else 0

            return {
                "dex": self.dex.get_name(),
                "hedged_pairs": hedged_pairs,
                "average_efficiency": avg_efficiency,
                "total_pairs": len(hedged_pairs),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error calculating hedging efficiency: {e}")
            return {
                "dex": self.dex.get_name(),
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def get_risk_metrics(self) -> Dict[str, Any]:
        """Calculate risk metrics for the portfolio"""
        try:
            futures_balance = self.dex.get_futures_balance()
            positions = self.dex.get_futures_positions()

            total_wallet_balance = float(futures_balance.get("totalWalletBalance", 0))
            total_unrealized_pnl = float(futures_balance.get("totalUnrealizedProfit", 0))
            total_margin_balance = float(futures_balance.get("totalMarginBalance", 0))

            # Calculate position exposure
            total_notional = sum(
                abs(float(p.get("positionAmt", 0))) * float(p.get("markPrice", 0))
                for p in positions
            )

            leverage = total_notional / total_margin_balance if total_margin_balance > 0 else 0

            return {
                "dex": self.dex.get_name(),
                "total_wallet_balance": total_wallet_balance,
                "total_unrealized_pnl": total_unrealized_pnl,
                "total_margin_balance": total_margin_balance,
                "total_notional_exposure": total_notional,
                "effective_leverage": leverage,
                "margin_ratio": total_margin_balance / total_notional if total_notional > 0 else 0,
                "risk_level": self._assess_risk_level(leverage),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return {
                "dex": self.dex.get_name(),
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def get_funding_analytics(self, symbol: str = None, days: int = 30) -> Dict[str, Any]:
        """Get funding fee analytics and projections"""
        try:
            # Get funding payments for different periods
            payments_1d = self.dex.get_funding_payments(symbol, days=1)
            payments_7d = self.dex.get_funding_payments(symbol, days=7)
            payments_30d = self.dex.get_funding_payments(symbol, days=30)
            payments_90d = self.dex.get_funding_payments(symbol, days=90)

            # Calculate totals
            total_1d = sum(float(p.get("income", 0)) for p in payments_1d)
            total_7d = sum(float(p.get("income", 0)) for p in payments_7d)
            total_30d = sum(float(p.get("income", 0)) for p in payments_30d)
            total_90d = sum(float(p.get("income", 0)) for p in payments_90d)

            # Calculate averages
            avg_daily_7d = total_7d / 7 if total_7d != 0 else 0
            avg_daily_30d = total_30d / 30 if total_30d != 0 else 0

            # Get current position size for rate calculations
            positions = self.dex.get_futures_positions()
            position_size = 0
            if symbol:
                position = next((p for p in positions if p.get("symbol") == symbol), None)
                if position:
                    position_size = abs(float(position.get("positionAmt", 0)))

            # Calculate effective funding rates (assuming 3 funding periods per day)
            effective_rate_7d = 0
            effective_rate_30d = 0
            if position_size > 0:
                position_value_approx = position_size * 2.0  # Approximate value
                if total_7d != 0:
                    effective_rate_7d = (total_7d / (position_value_approx * 7 * 3)) * 100
                if total_30d != 0:
                    effective_rate_30d = (total_30d / (position_value_approx * 30 * 3)) * 100

            return {
                "dex": self.dex.get_name(),
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "position_size": position_size,
                "funding_totals": {
                    "1_day": total_1d,
                    "7_days": total_7d,
                    "30_days": total_30d,
                    "90_days": total_90d
                },
                "daily_averages": {
                    "7_day_avg": avg_daily_7d,
                    "30_day_avg": avg_daily_30d
                },
                "effective_rates": {
                    "7_day_rate_percent": effective_rate_7d,
                    "30_day_rate_percent": effective_rate_30d
                },
                "projections": {
                    "monthly_projected": avg_daily_30d * 30,
                    "yearly_projected": avg_daily_30d * 365
                },
                "payment_counts": {
                    "1_day": len(payments_1d),
                    "7_days": len(payments_7d),
                    "30_days": len(payments_30d),
                    "90_days": len(payments_90d)
                },
                "recent_payments": payments_7d[:10] if payments_7d else []
            }

        except Exception as e:
            logger.error(f"Error getting funding analytics: {e}")
            return {
                "dex": self.dex.get_name(),
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def get_position_pnl(self) -> Dict[str, Any]:
        """Calculate PnL for all positions"""
        try:
            positions = self.dex.get_futures_positions()
            total_pnl = Decimal("0")
            position_details = []

            for pos in positions:
                symbol = pos.get("symbol", "")
                position_amt = Decimal(pos.get("positionAmt", "0"))
                entry_price = Decimal(pos.get("entryPrice", "0"))
                mark_price = Decimal(pos.get("markPrice", "0"))
                unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))

                if position_amt != 0:
                    position_details.append({
                        "symbol": symbol,
                        "position_amt": str(position_amt),
                        "entry_price": str(entry_price),
                        "mark_price": str(mark_price),
                        "unrealized_pnl": str(unrealized_pnl),
                        "side": "LONG" if position_amt > 0 else "SHORT"
                    })
                    total_pnl += unrealized_pnl

            return {
                "dex": self.dex.get_name(),
                "total_unrealized_pnl": str(total_pnl),
                "positions": position_details,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error calculating PnL: {e}")
            return {
                "dex": self.dex.get_name(),
                "total_unrealized_pnl": "0",
                "positions": [],
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def get_mark_price_context(
        self,
        symbol: str = "ASTERUSDT",
        interval: str = "5m",
        limit: int = 12,
    ) -> Dict[str, Any]:
        """Fetch mark price metadata and kline history for APY insight"""
        try:
            raw_info = self.dex.get_mark_price(symbol)
            if isinstance(raw_info, list):
                mark_info = next(
                    (item for item in raw_info if item.get("symbol") == symbol),
                    raw_info[0] if raw_info else {},
                )
            else:
                mark_info = raw_info or {}

            klines_raw = self.dex.get_mark_price_klines(symbol, interval, limit=limit)

            formatted_klines = []
            for entry in klines_raw or []:
                try:
                    formatted_klines.append(
                        {
                            "open_time": entry[0],
                            "open_price": float(entry[1]),
                            "high_price": float(entry[2]),
                            "low_price": float(entry[3]),
                            "close_price": float(entry[4]),
                            "close_time": entry[6],
                            "bar_count": int(entry[8]) if len(entry) > 8 else 0,
                        }
                    )
                except Exception:
                    continue

            last_funding_rate = float(mark_info.get("lastFundingRate", 0) or 0)
            last_funding_rate_percent = last_funding_rate * 100
            # Funding rates accrue every 8 hours. Annualised APY ≈ rate_per_period * 3 periods/day * 365 days.
            estimated_apy_percent = last_funding_rate * 3 * 365 * 100

            next_funding_time = mark_info.get("nextFundingTime")
            next_funding_iso: Optional[str] = None
            if next_funding_time:
                try:
                    next_funding_iso = datetime.fromtimestamp(
                        int(next_funding_time) / 1000
                    ).isoformat()
                except Exception:
                    next_funding_iso = None

            return {
                "symbol": symbol,
                "mark_price": float(mark_info.get("markPrice", 0) or 0),
                "index_price": float(mark_info.get("indexPrice", 0) or 0),
                "last_funding_rate": last_funding_rate,
                "last_funding_rate_percent": last_funding_rate_percent,
                "estimated_apy_percent": estimated_apy_percent,
                "interest_rate": float(mark_info.get("interestRate", 0) or 0),
                "next_funding_time": next_funding_time,
                "next_funding_time_iso": next_funding_iso,
                "estimated_settle_price": float(mark_info.get("estimatedSettlePrice", 0) or 0),
                "klines_interval": interval,
                "klines_limit": limit,
                "klines": formatted_klines,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error fetching mark price context: {e}")
            return {
                "dex": self.dex.get_name(),
                "symbol": symbol,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def _assess_risk_level(self, leverage: float) -> str:
        """Assess risk level based on leverage"""
        if leverage < 2:
            return "LOW"
        elif leverage < 5:
            return "MEDIUM"
        elif leverage < 10:
            return "HIGH"
        else:
            return "EXTREME"

    def _get_price_usd(self, asset: str) -> float:
        """Get USD price for an asset"""
        try:
            if asset == "USDT" or asset == "USD":
                return 1.0

            # Try to get price from spot API
            symbol = f"{asset}USDT"
            price = self.dex.get_spot_price(symbol)
            return float(price)
        except:
            return 0.0
