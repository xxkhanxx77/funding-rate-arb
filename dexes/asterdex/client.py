#!/usr/bin/env python3
"""
AsterDex API client implementation
Refactored from the original funding_bot.py
"""

import hashlib
import hmac
import time
import requests
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlencode

from ..base.dex_interface import BaseDexInterface

logger = logging.getLogger(__name__)


class AsterDexClient(BaseDexInterface):
    """AsterDex API client implementation"""

    def __init__(self, api_key: str, api_secret: str, recv_window: int = 5000):
        super().__init__(api_key, api_secret)
        self.spot_base_url = "https://sapi.asterdex.com"
        self.futures_base_url = "https://fapi.asterdex.com"
        self.recv_window = recv_window
        self._api_secret = api_secret.encode("utf-8")

        # Setup session
        self._session = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "AsterDexClient/1.0",
        })

        # Cache for symbol info
        self._spot_symbol_cache = {}
        self._futures_symbol_cache = {}

    def get_name(self) -> str:
        return "AsterDex"

    def get_spot_balance(self) -> List[Dict[str, Any]]:
        """Get spot account balance using AsterDx endpoint"""
        try:
            data = self._request(
                self.spot_base_url,
                "/api/v1/account",
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
            return self._request(
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
            positions = self._request(
                self.futures_base_url,
                "/fapi/v2/positionRisk",
                signed=True
            )
            # Filter out positions with zero size
            return [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        except Exception as e:
            logger.error(f"Error getting futures positions: {e}")
            return []

    def get_funding_payments(self, symbol: str = None, days: int = 7) -> List[Dict[str, Any]]:
        """Get funding payment history using AsterDex futures API"""
        try:
            from datetime import datetime, timedelta
            start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
            params = {
                "incomeType": "FUNDING_FEE",
                "startTime": start_time,
                "limit": 1000
            }
            if symbol:
                params["symbol"] = symbol

            funding_history = self._request(
                self.futures_base_url,
                "/fapi/v1/income",
                params=params,
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
            logger.error(f"Error getting funding payments: {e}")
            return []

    def get_spot_price(self, symbol: str) -> Decimal:
        """Get current spot price"""
        try:
            data = self._request(
                self.spot_base_url,
                "/api/v1/ticker/price",
                params={"symbol": symbol}
            )
            return Decimal(data["price"])
        except Exception as e:
            logger.error(f"Error getting spot price for {symbol}: {e}")
            raise

    def get_futures_price(self, symbol: str) -> Decimal:
        """Get current futures price"""
        try:
            data = self._request(
                self.futures_base_url,
                "/fapi/v1/ticker/price",
                params={"symbol": symbol}
            )
            return Decimal(data["price"])
        except Exception as e:
            logger.error(f"Error getting futures price for {symbol}: {e}")
            raise

    def place_spot_market_buy(self, symbol: str, quote_amount: Decimal) -> Dict[str, Any]:
        """Place a spot market buy order"""
        try:
            payload = {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": self._decimal_to_str(quote_amount),
                "newOrderRespType": "FULL",
            }
            return self._request(
                self.spot_base_url,
                "/api/v1/order",
                method="POST",
                params=payload,
                signed=True
            )
        except Exception as e:
            logger.error(f"Error placing spot buy order: {e}")
            raise

    def place_spot_market_sell(self, symbol: str, base_amount: Decimal) -> Dict[str, Any]:
        """Place a spot market sell order"""
        try:
            payload = {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": self._decimal_to_str(base_amount),
                "newOrderRespType": "FULL",
            }
            return self._request(
                self.spot_base_url,
                "/api/v1/order",
                method="POST",
                params=payload,
                signed=True
            )
        except Exception as e:
            logger.error(f"Error placing spot sell order: {e}")
            raise

    def place_futures_market_long(self, symbol: str, quantity: Decimal) -> Dict[str, Any]:
        """Place a futures market long order"""
        try:
            payload = {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": self._decimal_to_str(quantity),
                "newOrderRespType": "RESULT",
            }
            return self._request(
                self.futures_base_url,
                "/fapi/v1/order",
                method="POST",
                params=payload,
                signed=True
            )
        except Exception as e:
            logger.error(f"Error placing futures long order: {e}")
            raise

    def place_futures_market_short(self, symbol: str, quantity: Decimal) -> Dict[str, Any]:
        """Place a futures market short order"""
        try:
            payload = {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": self._decimal_to_str(quantity),
                "newOrderRespType": "RESULT",
            }
            return self._request(
                self.futures_base_url,
                "/fapi/v1/order",
                method="POST",
                params=payload,
                signed=True
            )
        except Exception as e:
            logger.error(f"Error placing futures short order: {e}")
            raise

    def get_symbol_info(self, symbol: str, market_type: str = "spot") -> Dict[str, Any]:
        """Get symbol trading information"""
        try:
            if market_type == "spot":
                if symbol not in self._spot_symbol_cache:
                    exchange_info = self._request(self.spot_base_url, "/api/v1/exchangeInfo")
                    for sym_info in exchange_info.get("symbols", []):
                        if sym_info.get("symbol") == symbol:
                            self._spot_symbol_cache[symbol] = sym_info
                            break
                return self._spot_symbol_cache.get(symbol, {})
            else:  # futures
                if symbol not in self._futures_symbol_cache:
                    exchange_info = self._request(self.futures_base_url, "/fapi/v1/exchangeInfo")
                    for sym_info in exchange_info.get("symbols", []):
                        if sym_info.get("symbol") == symbol:
                            self._futures_symbol_cache[symbol] = sym_info
                            break
                return self._futures_symbol_cache.get(symbol, {})
        except Exception as e:
            logger.error(f"Error getting symbol info for {symbol}: {e}")
            return {}

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Set leverage for a futures symbol"""
        try:
            return self._request(
                self.futures_base_url,
                '/fapi/v1/leverage',
                method='POST',
                params={
                    'symbol': symbol,
                    'leverage': leverage
                },
                signed=True
            )
        except Exception as e:
            logger.error(f"Error setting leverage for {symbol}: {e}")
            raise

    def get_mark_price(self, symbol: Optional[str] = None) -> Any:
        """Get current mark price metadata"""
        try:
            params = {"symbol": symbol} if symbol else None
            return self._request(
                self.futures_base_url,
                "/fapi/v1/premiumIndex",
                params=params,
            )
        except Exception as e:
            logger.error(f"Error getting mark price for {symbol or 'ALL'}: {e}")
            raise

    def get_mark_price_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 12,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[List[Any]]:
        """Get mark price kline/candlestick data"""
        try:
            params: Dict[str, Any] = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            }
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time

            return self._request(
                self.futures_base_url,
                "/fapi/v1/markPriceKlines",
                params=params,
            )
        except Exception as e:
            logger.error(f"Error getting mark price klines for {symbol}: {e}")
            raise

    # Helper methods
    def _request(
        self,
        base_url: str,
        path: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        """Make API request"""
        url = f"{base_url}{path}"
        params = params or {}

        if signed:
            request_params = self._sign_params(params)
        else:
            request_params = dict(params)

        if method.upper() == "GET":
            response = self._session.get(url, params=request_params, timeout=10)
        else:
            response = self._session.request(method.upper(), url, data=request_params, timeout=10)

        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

        data = response.json()
        if isinstance(data, dict) and "code" in data and data.get("code") not in (0, "0"):
            raise RuntimeError(f"API error: {data}")
        return data

    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sign request parameters"""
        payload = dict(params)
        payload.setdefault("recvWindow", self.recv_window)
        payload["timestamp"] = int(time.time() * 1000)
        query = urlencode(payload, doseq=True)
        signature = hmac.new(self._api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = signature
        return payload

    def _decimal_to_str(self, value: Decimal) -> str:
        """Convert Decimal to string format"""
        s = format(value, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"

    def _floor_to_step(self, value: Decimal, step: Decimal) -> Decimal:
        """Floor value to step size"""
        if step <= 0:
            return value
        remainder = value % step
        return (value - remainder).quantize(step, rounding=ROUND_DOWN)

    def get_lot_size_info(self, symbol: str, market_type: str = "futures") -> Tuple[Decimal, Decimal]:
        """Get step size and minimum quantity for a symbol"""
        symbol_info = self.get_symbol_info(symbol, market_type)
        for flt in symbol_info.get("filters", []):
            if flt.get("filterType") == "LOT_SIZE":
                step = Decimal(flt["stepSize"])
                min_qty = Decimal(flt["minQty"])
                return step, min_qty
        raise RuntimeError(f"LOT_SIZE filter not found for {symbol}")

    def get_min_notional(self, symbol: str, market_type: str = "futures") -> Decimal:
        """Get minimum notional value for a symbol"""
        symbol_info = self.get_symbol_info(symbol, market_type)
        for flt in symbol_info.get("filters", []):
            if flt.get("filterType") == "MIN_NOTIONAL":
                return Decimal(flt.get("minNotional") or flt.get("notional") or "0")
        return Decimal("0")
