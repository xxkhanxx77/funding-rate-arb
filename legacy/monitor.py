#!/usr/bin/env python3
import os
import time
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional
from legacy.funding_bot import AsterDexFundingBot
import requests

logger = logging.getLogger(__name__)

class AsterDexMonitor:
    """Monitor for AsterDex positions and account status"""

    def __init__(self):
        self.spot_base_url = "https://sapi.asterdex.com"
        self.futures_base_url = "https://fapi.asterdex.com"

        api_key = os.environ.get("ASTERDEX_API_KEY") 
        api_secret = os.environ.get("ASTERDEX_API_SECRET") 

        self._api_key = api_key
        self._api_secret = api_secret.encode("utf-8")

        self._session = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self._api_key,
            "User-Agent": "AsterMonitor/0.1",
        })

        # Use the same signing method as the bot
        self._bot = AsterDexFundingBot(capital_usd=Decimal("200"), batch_quote=Decimal("200"))  # Dummy instance for utility methods

    def get_account_summary(self) -> Dict[str, Any]:
        """Get comprehensive account summary"""
        try:
            spot_balance = self.get_spot_balance()
            futures_balance = self.get_futures_balance()
            futures_positions = self.get_futures_positions()
            funding_info = self.get_funding_info()

            # Calculate total portfolio value
            total_spot_usd = sum(
                float(asset.get("free", 0)) * self._get_price_usd(asset["asset"])
                for asset in spot_balance
            )

            total_futures_usd = float(futures_balance.get("totalWalletBalance", 0))

            return {
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
                "funding": funding_info,
                "portfolio": {
                    "total_usd": total_spot_usd + total_futures_usd,
                    "spot_ratio": total_spot_usd / (total_spot_usd + total_futures_usd) if (total_spot_usd + total_futures_usd) > 0 else 0,
                    "futures_ratio": total_futures_usd / (total_spot_usd + total_futures_usd) if (total_spot_usd + total_futures_usd) > 0 else 0
                }
            }
        except Exception as e:
            logger.error(f"Error getting account summary: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "spot": {"balance": [], "total_usd": 0},
                "futures": {"balance": {}, "positions": [], "total_usd": 0},
                "funding": [],
                "portfolio": {"total_usd": 0, "spot_ratio": 0, "futures_ratio": 0}
            }

    def get_spot_balance(self) -> List[Dict[str, Any]]:
        """Get spot account balance using correct AsterDex endpoint"""
        try:
            # Use the correct AsterDex spot API endpoint from documentation
            data = self._bot._request(
                self.spot_base_url,
                "/api/v1/account",  # Correct endpoint per AsterDex docs
                signed=True
            )
            balances = data.get("balances", [])
            # Filter out zero balances
            return [b for b in balances if float(b.get("free", 0)) > 0 or float(b.get("locked", 0)) > 0]
        except Exception as e:
            logger.error(f"Error getting spot balance: {e}")
            return []

    def get_futures_balance(self) -> Dict[str, Any]:
        """Get futures account balance"""
        try:
            return self._bot._request(
                self.futures_base_url,
                "/fapi/v2/account",
                signed=True
            )
        except Exception as e:
            logger.error(f"Error getting futures balance: {e}")
            return {}

    def get_futures_positions(self) -> List[Dict[str, Any]]:
        """Get current futures positions"""
        try:
            positions = self._bot._request(
                self.futures_base_url,
                "/fapi/v2/positionRisk",
                signed=True
            )
            # Filter out positions with zero size
            return [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        except Exception as e:
            logger.error(f"Error getting futures positions: {e}")
            return []

    def get_funding_info(self, symbols: List[str] = None) -> List[Dict[str, Any]]:
        """Get funding rate information for symbols"""
        try:
            if not symbols:
                symbols = ["ASTERUSDT", "BTCUSDT", "ETHUSDT"]  # Default symbols

            funding_info = []
            for symbol in symbols:
                try:
                    # Get current funding rate
                    funding_rate = self._bot._request(
                        self.futures_base_url,
                        "/fapi/v1/fundingRate",
                        params={"symbol": symbol, "limit": 1}
                    )

                    # Get premium index (funding rate preview)
                    premium = self._bot._request(
                        self.futures_base_url,
                        "/fapi/v1/premiumIndex",
                        params={"symbol": symbol}
                    )

                    funding_info.append({
                        "symbol": symbol,
                        "current_funding_rate": funding_rate[0] if funding_rate else {},
                        "premium_index": premium
                    })
                except Exception as e:
                    logger.warning(f"Could not get funding info for {symbol}: {e}")

            return funding_info
        except Exception as e:
            logger.error(f"Error getting funding info: {e}")
            return []

    def get_position_pnl(self) -> Dict[str, Any]:
        """Calculate PnL for all positions"""
        try:
            positions = self.get_futures_positions()
            total_pnl = Decimal("0")
            position_details = []

            for position in positions:
                symbol = position.get("symbol", "")
                position_amt = Decimal(position.get("positionAmt", "0"))
                entry_price = Decimal(position.get("entryPrice", "0"))
                mark_price = Decimal(position.get("markPrice", "0"))
                unrealized_pnl = Decimal(position.get("unRealizedProfit", "0"))

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
                "total_unrealized_pnl": str(total_pnl),
                "positions": position_details,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error calculating PnL: {e}")
            return {
                "total_unrealized_pnl": "0",
                "positions": [],
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def get_funding_payments(self, symbol: str = None, days: int = 7) -> List[Dict[str, Any]]:
        """Get funding payment history using AsterDex futures API"""
        try:
            start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
            params = {
                "startTime": start_time,
                "limit": 1000
            }
            if symbol:
                params["symbol"] = symbol

            # Use the correct AsterDex futures funding history endpoint
            funding_history = self._bot._request(
                self.futures_base_url,
                "/fapi/v1/income",  # AsterDex uses /fapi/v1/income for funding payments
                params={**params, "incomeType": "FUNDING_FEE"},
                signed=True
            )

            # Filter and format funding payments
            payments = []
            for payment in funding_history:
                if payment.get("incomeType") == "FUNDING_FEE":
                    payments.append({
                        "symbol": payment.get("symbol"),
                        "income": payment.get("income"),
                        "asset": payment.get("asset"),
                        "info": payment.get("info"),
                        "time": payment.get("time"),
                        "tranId": payment.get("tranId"),
                        "tradeId": payment.get("tradeId")
                    })

            return payments

        except Exception as e:
            logger.warning(f"Error getting funding payments (trying fallback): {e}")

            # Fallback to original endpoint if available
            try:
                start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
                params = {
                    "startTime": start_time,
                    "limit": 1000
                }
                if symbol:
                    params["symbol"] = symbol

                return self._bot._request(
                    self.futures_base_url,
                    "/fapi/v1/fundingHistory",  # Original endpoint as fallback
                    params=params,
                    signed=True
                )
            except Exception as e2:
                logger.error(f"Error getting funding payments (both methods failed): {e2}")
                return []

    def _get_price_usd(self, asset: str) -> float:
        """Get USD price for an asset"""
        try:
            if asset == "USDT" or asset == "USD":
                return 1.0

            # Try to get price from spot API
            symbol = f"{asset}USDT"
            price_data = self._bot._request(
                self.spot_base_url,
                "/api/v3/ticker/price",
                params={"symbol": symbol}
            )
            return float(price_data.get("price", 0))
        except:
            return 0.0

    def get_risk_metrics(self) -> Dict[str, Any]:
        """Calculate risk metrics for the portfolio"""
        try:
            futures_balance = self.get_futures_balance()
            positions = self.get_futures_positions()

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
                "error": str(e),
                "timestamp": datetime.now().isoformat()
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

    def get_hedging_efficiency(self) -> Dict[str, Any]:
        """Calculate hedging efficiency between spot and futures"""
        try:
            spot_balance = self.get_spot_balance()
            futures_positions = self.get_futures_positions()

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
                "hedged_pairs": hedged_pairs,
                "average_efficiency": avg_efficiency,
                "total_pairs": len(hedged_pairs),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error calculating hedging efficiency: {e}")
            return {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


if __name__ == "__main__":
    monitor = AsterDexMonitor()

    print("=== AsterDex Portfolio Monitor ===")
    print()

    # Test spot balance with correct endpoint
    print("Spot Balance:")
    spot_balance = monitor.get_spot_balance()
    if spot_balance:
        for asset in spot_balance:
            print(f"  {asset['asset']}: Free={asset['free']}, Locked={asset['locked']}")
    else:
        print("  No spot balance found or error occurred")

    print()

    # Test futures positions
    print("Futures Positions:")
    futures_positions = monitor.get_futures_positions()
    if futures_positions:
        for pos in futures_positions:
            print(f"  {pos['symbol']}: {pos['positionAmt']} @ {pos['entryPrice']} (PnL: {pos['unRealizedProfit']})")
    else:
        print("  No futures positions found")

    print()

    # Test hedging efficiency
    print("Hedging Status:")
    hedging = monitor.get_hedging_efficiency()
    if "error" not in hedging:
        if hedging['hedged_pairs']:
            for pair in hedging['hedged_pairs']:
                print(f"  {pair['symbol']}: Spot={pair['spot_qty']:.4f}, Futures={pair['futures_qty']:.4f}, Ratio={pair['hedge_ratio']:.2%}")
            print(f"  Average Efficiency: {hedging['average_efficiency']:.2%}")

            # Determine strategy status
            if hedging['total_pairs'] > 0 and hedging['average_efficiency'] > 0.8:
                print("  Strategy Status: ACTIVE ✓")
            else:
                print("  Strategy Status: Inactive")
        else:
            print("  No hedged pairs found")
            print("  Strategy Status: Inactive")
    else:
        print(f"  Error: {hedging['error']}")

    print()

    # Test PnL
    pnl = monitor.get_position_pnl()
    print(f"Total Unrealized PnL: ${pnl['total_unrealized_pnl']}")

    print("\n=== End Monitor ===")
