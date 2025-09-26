#!/usr/bin/env python3
"""
AsterDex Funding Bot Implementation
Refactored from the original funding_bot.py
"""

import time
import json
import logging
from decimal import Decimal
from typing import Dict, Any, List
from datetime import datetime

from ..base.dex_interface import BaseFundingBot
from .client import AsterDexClient

logger = logging.getLogger(__name__)

MODE_BUY_SPOT_SHORT_FUTURES = "buy_spot_short_futures"
MODE_SELL_SPOT_LONG_FUTURES = "sell_spot_long_futures"


class AsterDexFundingBot(BaseFundingBot):
    """AsterDex funding fee farming bot implementation"""

    def __init__(
        self,
        dex: AsterDexClient,
        capital_usd: Decimal,
        spot_symbol: str = "ASTERUSDT",
        futures_symbol: str = "ASTERUSDT",
        batch_quote: Decimal = Decimal("200"),
        batch_delay: float = 1.0,
        mode: str = MODE_BUY_SPOT_SHORT_FUTURES,
        **kwargs
    ):
        super().__init__(dex, capital_usd)
        self.spot_symbol = spot_symbol.upper()
        self.futures_symbol = futures_symbol.upper()
        self.batch_quote = batch_quote
        self.batch_delay = batch_delay
        self.mode = mode

        # Validate inputs
        if self.mode not in {MODE_BUY_SPOT_SHORT_FUTURES, MODE_SELL_SPOT_LONG_FUTURES}:
            raise ValueError(f"Unsupported mode: {self.mode}")

        if self.capital_usd <= 0:
            raise ValueError("Capital must be greater than zero")

        if self.batch_quote <= 0:
            raise ValueError("Batch quote must be greater than zero")

        # Calculate batch count
        batches, remainder = divmod(self.capital_usd, self.batch_quote)
        if remainder != 0:
            raise ValueError("Capital must be an exact multiple of the batch quote size")

        self.batch_count = int(batches)
        if self.batch_count <= 0:
            raise ValueError("Batch configuration results in zero orders")

    def execute_strategy(self, symbol: str = None, **kwargs) -> Dict[str, Any]:
        """Execute the funding fee farming strategy"""
        if symbol:
            self.spot_symbol = symbol
            self.futures_symbol = symbol

        logger.info(f"Starting {self.dex.get_name()} funding bot execution")
        logger.info(f"Mode: {self.mode}, Capital: {self.capital_usd}, Batches: {self.batch_count}")

        # Get symbol information
        spot_symbol_info = self.dex.get_symbol_info(self.spot_symbol, "spot")
        futures_symbol_info = self.dex.get_symbol_info(self.futures_symbol, "futures")

        if not spot_symbol_info or not futures_symbol_info:
            raise RuntimeError("Failed to get symbol information")

        # Get initial price for calculations
        initial_spot_price = self.dex.get_spot_price(self.spot_symbol)
        theoretical_base_qty = self.capital_usd / initial_spot_price

        # Get lot size information
        spot_step, spot_min_qty = self.dex.get_lot_size_info(self.spot_symbol, "spot")
        futures_step, futures_min_qty = self.dex.get_lot_size_info(self.futures_symbol, "futures")
        futures_min_notional = self.dex.get_min_notional(self.futures_symbol, "futures")

        logger.info(f"Symbol info loaded - Spot step: {spot_step}, Futures step: {futures_step}")

        # Execute batches
        total_quote_spent = Decimal("0")
        total_base_qty = Decimal("0")
        total_futures_qty = Decimal("0")
        spot_orders = []
        futures_orders = []

        reverse_mode = self.mode == MODE_SELL_SPOT_LONG_FUTURES

        for batch_index in range(self.batch_count):
            logger.info(f"Executing batch {batch_index + 1}/{self.batch_count}")

            # Place spot order
            if reverse_mode:
                spot_price = self.dex.get_spot_price(self.spot_symbol)
                target_qty = self.batch_quote / spot_price
                spot_qty = self.dex._floor_to_step(target_qty, spot_step)

                if spot_qty < spot_min_qty:
                    raise RuntimeError(f"Spot quantity below minimum: {spot_qty} < {spot_min_qty}")

                spot_order = self.dex.place_spot_market_sell(self.spot_symbol, spot_qty)
            else:
                spot_order = self.dex.place_spot_market_buy(self.spot_symbol, self.batch_quote)

            # Process spot order result
            executed_spot_qty = Decimal(spot_order.get("executedQty", "0"))
            if executed_spot_qty <= 0:
                spot_order = self._wait_for_order_fill(spot_order, "spot")
                executed_spot_qty = Decimal(spot_order.get("executedQty", "0"))

            quote_spent = self._extract_quote_filled(spot_order)
            if executed_spot_qty <= 0 or quote_spent <= 0:
                raise RuntimeError(f"Spot order failed: {json.dumps(spot_order)}")

            total_quote_spent += quote_spent
            total_base_qty += executed_spot_qty

            logger.info(f"Spot order filled: {executed_spot_qty} @ {quote_spent} USDT")

            # Place futures hedge order
            futures_qty = self.dex._floor_to_step(executed_spot_qty, futures_step)

            if futures_qty < futures_min_qty:
                raise RuntimeError(f"Futures quantity below minimum: {futures_qty} < {futures_min_qty}")

            # Check minimum notional
            futures_price = self.dex.get_futures_price(self.futures_symbol)
            projected_notional = futures_qty * futures_price
            if futures_min_notional > 0 and projected_notional < futures_min_notional:
                raise RuntimeError(f"Futures notional below minimum: {projected_notional} < {futures_min_notional}")

            if reverse_mode:
                futures_order = self.dex.place_futures_market_long(self.futures_symbol, futures_qty)
            else:
                futures_order = self.dex.place_futures_market_short(self.futures_symbol, futures_qty)

            # Process futures order result
            executed_futures_qty = Decimal(futures_order.get("executedQty", self.dex._decimal_to_str(futures_qty)))
            if executed_futures_qty <= 0:
                futures_order = self._wait_for_order_fill(futures_order, "futures")
                executed_futures_qty = Decimal(futures_order.get("executedQty", self.dex._decimal_to_str(futures_qty)))

            if executed_futures_qty <= 0:
                raise RuntimeError(f"Futures order failed: {json.dumps(futures_order)}")

            total_futures_qty += executed_futures_qty

            logger.info(f"Futures order filled: {executed_futures_qty}")

            # Store order details
            spot_orders.append({
                "orderId": spot_order.get("orderId"),
                "status": spot_order.get("status"),
                "executedQty": self.dex._decimal_to_str(executed_spot_qty),
                "quoteSpent": self.dex._decimal_to_str(quote_spent),
                "updateTime": spot_order.get("updateTime"),
                "fills": spot_order.get("fills", []),
            })

            futures_orders.append({
                "orderId": futures_order.get("orderId"),
                "status": futures_order.get("status"),
                "executedQty": self.dex._decimal_to_str(executed_futures_qty),
                "requestedQty": self.dex._decimal_to_str(futures_qty),
                "avgPrice": futures_order.get("avgPrice"),
                "updateTime": futures_order.get("updateTime"),
            })

            # Delay between batches
            if batch_index < self.batch_count - 1:
                logger.info(f"Waiting {self.batch_delay}s before next batch")
                time.sleep(self.batch_delay)

        result = {
            "dex": self.dex.get_name(),
            "mode": self.mode,
            "timestamp": datetime.now().isoformat(),
            "spot": {
                "symbol": self.spot_symbol,
                "totalExecutedQty": self.dex._decimal_to_str(total_base_qty),
                "totalQuoteSpent": self.dex._decimal_to_str(total_quote_spent),
                "orders": spot_orders,
            },
            "futures": {
                "symbol": self.futures_symbol,
                "totalExecutedQty": self.dex._decimal_to_str(total_futures_qty),
                "orders": futures_orders,
            },
            "targets": {
                "capitalUsd": self.dex._decimal_to_str(self.capital_usd),
                "theoreticalBaseQty": self.dex._decimal_to_str(theoretical_base_qty),
                "batchQuote": self.dex._decimal_to_str(self.batch_quote),
                "batchCount": self.batch_count,
            },
        }

        logger.info(f"Strategy execution completed successfully")
        return result

    def get_strategy_status(self) -> Dict[str, Any]:
        """Get current strategy status"""
        try:
            spot_balance = self.dex.get_spot_balance()
            futures_positions = self.dex.get_futures_positions()

            # Find ASTER positions
            aster_spot = 0
            for asset in spot_balance:
                if asset.get("asset") == "ASTER":
                    aster_spot = float(asset.get("free", 0))
                    break

            aster_futures = 0
            aster_futures_pnl = 0
            for pos in futures_positions:
                if pos.get("symbol") == "ASTERUSDT":
                    aster_futures = abs(float(pos.get("positionAmt", 0)))
                    aster_futures_pnl = float(pos.get("unRealizedProfit", 0))
                    break

            # Calculate hedge ratio
            hedge_ratio = aster_futures / aster_spot if aster_spot > 0 else 0
            is_active = aster_spot > 0 and aster_futures > 0
            health = "HEALTHY" if 0.95 <= hedge_ratio <= 1.05 else "NEEDS_ATTENTION"

            return {
                "dex": self.dex.get_name(),
                "is_active": is_active,
                "health": health,
                "hedge_ratio": hedge_ratio,
                "spot_aster": aster_spot,
                "futures_aster": aster_futures,
                "futures_pnl": aster_futures_pnl,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting strategy status: {e}")
            return {
                "dex": self.dex.get_name(),
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def _wait_for_order_fill(self, order: Dict[str, Any], order_type: str, retries: int = 5, delay: float = 1.0) -> Dict[str, Any]:
        """Wait for order to fill"""
        order_id = order.get("orderId")
        if not order_id:
            return order

        symbol = self.spot_symbol if order_type == "spot" else self.futures_symbol
        endpoint = "/api/v1/order" if order_type == "spot" else "/fapi/v1/order"
        base_url = self.dex.spot_base_url if order_type == "spot" else self.dex.futures_base_url

        last = order
        for attempt in range(retries):
            time.sleep(delay)
            try:
                last = self.dex._request(
                    base_url,
                    endpoint,
                    params={"symbol": symbol, "orderId": order_id},
                    signed=True,
                )

                status = last.get("status")
                logger.debug(f"{order_type.title()} order {order_id} status: {status}")

                if status in {"FILLED", "PARTIALLY_FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                    break

            except Exception as e:
                logger.warning(f"Error polling {order_type} order {order_id}: {e}")

        return last

    def _extract_quote_filled(self, order: Dict[str, Any]) -> Decimal:
        """Extract quote amount filled from order"""
        for key in ("cumQuote", "cummulativeQuoteQty", "executedQuoteQty"):
            if key in order:
                return Decimal(order[key])
        return Decimal("0")
