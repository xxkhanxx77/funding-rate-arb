#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import logging
import os
import time
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests


getcontext().prec = 28

DEFAULT_API_KEY = ""  # ตัวอย่างค่า API key หากไม่ดึงจาก environment
DEFAULT_API_SECRET = ""  # ตัวอย่างค่า API secret หากไม่ดึงจาก environment

DEFAULT_CAPITAL_USD = Decimal("200000")  # ทุนรวมฝั่งสปอตที่ต้องการ deploy ทั้งหมด (หน่วย USDT)
DEFAULT_SPOT_SYMBOL = "ASTERUSDT"  # คู่เทรดสปอตเริ่มต้นสำหรับฝั่งซื้อ/ขาย
DEFAULT_FUTURES_SYMBOL = "ASTERUSDT"  # สัญญาฟิวเจอร์สเริ่มต้นสำหรับฝั่ง hedge
DEFAULT_BATCH_QUOTE = Decimal("200")  # ขนาดคำสั่งต่อรอบในหน่วย quote (USDT) หรือประมาณการที่ใช้คำนวณปริมาณขาย
DEFAULT_BATCH_DELAY = 1.0  # เวลาหน่วงระหว่างรอบส่งคำสั่งแต่ละชุด (วินาที)
DEFAULT_LOG_LEVEL = "INFO"  # ระดับความละเอียดของ log ขณะรัน

MODE_BUY_SPOT_SHORT_FUTURES = "buy_spot_short_futures"  # โหมดซื้อสปอตและเปิดชอร์ตฟิวเจอร์สเพื่อ hedge
MODE_SELL_SPOT_LONG_FUTURES = "sell_spot_long_futures"  # โหมดขายสปอตและเปิดลองฟิวเจอร์สเพื่อ hedge
DEFAULT_MODE = MODE_BUY_SPOT_SHORT_FUTURES  # โหมดดีฟอลต์เมื่อไม่กำหนดผ่าน CLI


class ColorFormatter(logging.Formatter):
    _LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",   # Cyan
        logging.INFO: "\033[32m",    # Green
        logging.WARNING: "\033[33m", # Yellow
        logging.ERROR: "\033[31m",   # Red
        logging.CRITICAL: "\033[35m",# Magenta
    }
    _RESET = "\033[0m"

    def __init__(self, fmt: str, use_color: bool = True) -> None:
        super().__init__(fmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if self._use_color:
            color = self._LEVEL_COLORS.get(record.levelno)
            if color:
                message = f"{color}{message}{self._RESET}"
        return message


class AsterDexFundingBot:
    spot_base_url = "https://sapi.asterdex.com"
    futures_base_url = "https://fapi.asterdex.com"

    def __init__(
        self,
        capital_usd: Decimal,
        spot_symbol: str = DEFAULT_SPOT_SYMBOL,
        futures_symbol: str = DEFAULT_FUTURES_SYMBOL,
        recv_window: int = 5000,
        batch_quote: Decimal = DEFAULT_BATCH_QUOTE,
        batch_delay: float = DEFAULT_BATCH_DELAY,
        mode: str = DEFAULT_MODE,
    ) -> None:
        self.capital_usd = Decimal(capital_usd)
        self.spot_symbol = spot_symbol.upper()
        self.futures_symbol = futures_symbol.upper()
        self.recv_window = recv_window
        self.batch_quote = Decimal(batch_quote)
        self.batch_delay = batch_delay
        if mode not in {MODE_BUY_SPOT_SHORT_FUTURES, MODE_SELL_SPOT_LONG_FUTURES}:
            raise ValueError(f"unsupported mode: {mode}")
        self.mode = mode

        if self.capital_usd <= 0:
            raise ValueError("capital must be greater than zero")
        if self.batch_quote <= 0:
            raise ValueError("batch quote must be greater than zero")

        batches, remainder = divmod(self.capital_usd, self.batch_quote)
        if remainder != 0:
            raise ValueError("capital must be an exact multiple of the batch quote size")
        self.batch_count = int(batches)
        if self.batch_count <= 0:
            raise ValueError("batch configuration results in zero orders")

        api_key = os.environ.get("ASTERDEX_API_KEY") or DEFAULT_API_KEY
        api_secret = os.environ.get("ASTERDEX_API_SECRET") or DEFAULT_API_SECRET
        if not api_key or not api_secret:
            raise RuntimeError("Missing ASTERDEX_API_KEY or ASTERDEX_API_SECRET environment variables")

        self._api_key = api_key
        self._api_secret = api_secret.encode("utf-8")
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.debug(
            "Initializing bot | capital=%s | spot=%s | futures=%s | batches=%s | delay=%s | mode=%s",
            self.capital_usd,
            self.spot_symbol,
            self.futures_symbol,
            self.batch_count,
            self.batch_delay,
            self.mode,
        )

        self._session = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self._api_key,
            "User-Agent": "AsterFundingBot/0.1",
        })

        self._spot_symbol_info: Optional[Dict[str, Any]] = None
        self._futures_symbol_info: Optional[Dict[str, Any]] = None

    def execute(self) -> Dict[str, Any]:
        spot_symbol_info = self._get_spot_symbol_info()
        futures_symbol_info = self._get_futures_symbol_info()

        initial_spot_price = self._fetch_spot_price()
        theoretical_base_qty = self.capital_usd / initial_spot_price

        spot_step, spot_min_qty = self._extract_step_and_min_qty(spot_symbol_info)
        futures_step, futures_min_qty = self._extract_step_and_min_qty(futures_symbol_info)
        futures_min_notional = self._extract_min_notional(futures_symbol_info)
        self._logger.info(
            "Batch config ready | mode=%s | spot_price=%s | futures_step=%s | futures_min_qty=%s | futures_min_notional=%s",
            self.mode,
            initial_spot_price,
            futures_step,
            futures_min_qty,
            futures_min_notional,
        )

        total_quote_spent = Decimal("0")
        total_base_qty = Decimal("0")
        total_futures_qty = Decimal("0")
        spot_orders: List[Dict[str, Any]] = []
        futures_orders: List[Dict[str, Any]] = []

        reverse_mode = self.mode == MODE_SELL_SPOT_LONG_FUTURES
        for batch_index in range(self.batch_count):
            batch_quote = self.batch_quote
            if reverse_mode:
                spot_price = self._fetch_spot_price()
                target_qty = batch_quote / spot_price
                spot_qty = self._floor_to_step(target_qty, spot_step)
                if spot_qty < spot_min_qty:
                    raise RuntimeError(
                        "Spot quantity below minimum after rounding: "
                        f"target={target_qty}, rounded={spot_qty}, min={spot_min_qty}"
                    )
                self._logger.info(
                    "Placing spot batch %s/%s | side=SELL | qty=%s | est_quote=%s",
                    batch_index + 1,
                    self.batch_count,
                    spot_qty,
                    batch_quote,
                )
                spot_order = self._place_spot_market_sell(spot_qty)
            else:
                self._logger.info(
                    "Placing spot batch %s/%s | side=BUY | quote=%s",
                    batch_index + 1,
                    self.batch_count,
                    batch_quote,
                )
                spot_order = self._place_spot_market_buy(batch_quote)
            executed_spot_qty = Decimal(spot_order.get("executedQty", "0"))
            if executed_spot_qty <= 0:
                self._logger.debug("Spot order pending fill, polling orderId=%s", spot_order.get("orderId"))
                spot_order = self._wait_for_spot_fill(spot_order)
                executed_spot_qty = Decimal(spot_order.get("executedQty", "0"))
            quote_spent = self._extract_quote_filled(spot_order)
            if executed_spot_qty <= 0 or quote_spent <= 0:
                raise RuntimeError(f"Spot order did not fill: {json.dumps(spot_order)}")

            total_quote_spent += quote_spent
            total_base_qty += executed_spot_qty
            self._logger.info(
                "Spot filled | orderId=%s | qty=%s | quote=%s | status=%s",
                spot_order.get("orderId"),
                executed_spot_qty,
                quote_spent,
                spot_order.get("status"),
            )
            spot_orders.append({
                "orderId": spot_order.get("orderId"),
                "status": spot_order.get("status"),
                "executedQty": self._decimal_to_str(executed_spot_qty),
                "quoteSpent": self._decimal_to_str(quote_spent),
                "updateTime": spot_order.get("updateTime"),
                "fills": spot_order.get("fills", []),
            })

            futures_qty = self._floor_to_step(executed_spot_qty, futures_step)
            futures_side = "BUY" if reverse_mode else "SELL"
            self._logger.info(
                "Placing futures hedge | batch=%s | side=%s | qty=%s",
                batch_index + 1,
                futures_side,
                futures_qty,
            )
            if futures_qty < futures_min_qty:
                raise RuntimeError(
                    "Futures quantity below minimum after rounding: "
                    f"executed={executed_spot_qty}, rounded={futures_qty}, min={futures_min_qty}"
                )

            futures_price = self._fetch_futures_price()
            projected_notional = futures_qty * futures_price
            if futures_min_notional > 0 and projected_notional < futures_min_notional:
                raise RuntimeError(
                    "Futures notional below minimum: "
                    f"qty={futures_qty}, price={futures_price}, min={futures_min_notional}"
                )

            if reverse_mode:
                futures_order = self._place_futures_market_long(futures_qty)
            else:
                futures_order = self._place_futures_market_short(futures_qty)
            executed_futures_qty = Decimal(
                futures_order.get("executedQty", self._decimal_to_str(futures_qty))
            )
            if executed_futures_qty <= 0:
                self._logger.debug(
                    "Futures order pending fill, polling orderId=%s",
                    futures_order.get("orderId"),
                )
                futures_order = self._wait_for_futures_fill(futures_order)
                executed_futures_qty = Decimal(
                    futures_order.get("executedQty", self._decimal_to_str(futures_qty))
                )
            if executed_futures_qty <= 0:
                raise RuntimeError(f"Futures order did not fill: {json.dumps(futures_order)}")

            price_str = futures_order.get("avgPrice") or futures_order.get("price")
            try:
                effective_price = Decimal(price_str) if price_str else futures_price
            except Exception:
                effective_price = futures_price
            executed_notional = executed_futures_qty * effective_price

            total_futures_qty += executed_futures_qty
            self._logger.info(
                "Futures filled | orderId=%s | qty=%s | notional=%s | status=%s",
                futures_order.get("orderId"),
                executed_futures_qty,
                executed_notional,
                futures_order.get("status"),
            )
            futures_orders.append({
                "orderId": futures_order.get("orderId"),
                "status": futures_order.get("status"),
                "executedQty": self._decimal_to_str(executed_futures_qty),
                "requestedQty": self._decimal_to_str(futures_qty),
                "avgPrice": futures_order.get("avgPrice"),
                "markPrice": self._decimal_to_str(futures_price),
                "notional": self._decimal_to_str(executed_notional),
                "updateTime": futures_order.get("updateTime"),
            })

            if batch_index < self.batch_count - 1:
                self._logger.debug(
                    "Waiting %s seconds before next batch | completed=%s/%s",
                    self.batch_delay,
                    batch_index + 1,
                    self.batch_count,
                )
                time.sleep(self.batch_delay)

        return {
            "mode": self.mode,
            "spot": {
                "symbol": self.spot_symbol,
                "totalExecutedQty": self._decimal_to_str(total_base_qty),
                "totalQuoteSpent": self._decimal_to_str(total_quote_spent),
                "orders": spot_orders,
            },
            "futures": {
                "symbol": self.futures_symbol,
                "totalExecutedQty": self._decimal_to_str(total_futures_qty),
                "orders": futures_orders,
            },
            "targets": {
                "capitalUsd": self._decimal_to_str(self.capital_usd),
                "theoreticalBaseQty": self._decimal_to_str(theoretical_base_qty),
                "batchQuote": self._decimal_to_str(self.batch_quote),
                "batchCount": self.batch_count,
            },
        }

    def _place_spot_market_buy(self, quote_amount: Decimal) -> Dict[str, Any]:
        self._logger.debug(
            "Submitting spot market order | symbol=%s | quoteOrderQty=%s",
            self.spot_symbol,
            quote_amount,
        )
        payload = {
            "symbol": self.spot_symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": self._decimal_to_str(quote_amount),
            "newOrderRespType": "FULL",
        }
        return self._request(self.spot_base_url, "/api/v1/order", method="POST", params=payload, signed=True)

    def _place_spot_market_sell(self, base_amount: Decimal) -> Dict[str, Any]:
        self._logger.debug(
            "Submitting spot market order | symbol=%s | quantity=%s",
            self.spot_symbol,
            base_amount,
        )
        payload = {
            "symbol": self.spot_symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": self._decimal_to_str(base_amount),
            "newOrderRespType": "FULL",
        }
        return self._request(self.spot_base_url, "/api/v1/order", method="POST", params=payload, signed=True)

    def _place_futures_market_short(self, quantity: Decimal) -> Dict[str, Any]:
        self._logger.debug(
            "Submitting futures market order | symbol=%s | quantity=%s",
            self.futures_symbol,
            quantity,
        )
        payload = {
            "symbol": self.futures_symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": self._decimal_to_str(quantity),
            "newOrderRespType": "RESULT",
        }
        return self._request(self.futures_base_url, "/fapi/v1/order", method="POST", params=payload, signed=True)

    def _place_futures_market_long(self, quantity: Decimal) -> Dict[str, Any]:
        self._logger.debug(
            "Submitting futures market order | symbol=%s | quantity=%s",
            self.futures_symbol,
            quantity,
        )
        payload = {
            "symbol": self.futures_symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": self._decimal_to_str(quantity),
            "newOrderRespType": "RESULT",
        }
        return self._request(self.futures_base_url, "/fapi/v1/order", method="POST", params=payload, signed=True)

    def _fetch_spot_price(self) -> Decimal:
        data = self._request(self.spot_base_url, "/api/v1/ticker/price", params={"symbol": self.spot_symbol})
        return Decimal(data["price"])

    def _fetch_futures_price(self) -> Decimal:
        data = self._request(self.futures_base_url, "/fapi/v1/ticker/price", params={"symbol": self.futures_symbol})
        return Decimal(data["price"])

    def _get_spot_symbol_info(self) -> Dict[str, Any]:
        if self._spot_symbol_info is None:
            exchange_info = self._request(self.spot_base_url, "/api/v1/exchangeInfo")
            for symbol in exchange_info.get("symbols", []):
                if symbol.get("symbol") == self.spot_symbol:
                    self._spot_symbol_info = symbol
                    break
            if self._spot_symbol_info is None:
                raise RuntimeError(f"Spot symbol {self.spot_symbol} not found in exchangeInfo")
        return self._spot_symbol_info

    def _get_futures_symbol_info(self) -> Dict[str, Any]:
        if self._futures_symbol_info is None:
            exchange_info = self._request(self.futures_base_url, "/fapi/v1/exchangeInfo")
            for symbol in exchange_info.get("symbols", []):
                if symbol.get("symbol") == self.futures_symbol:
                    self._futures_symbol_info = symbol
                    break
            if self._futures_symbol_info is None:
                raise RuntimeError(f"Futures symbol {self.futures_symbol} not found in exchangeInfo")
        return self._futures_symbol_info

    def _extract_step_and_min_qty(self, symbol_info: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
        lot_filter = self._get_filter(symbol_info, "LOT_SIZE")
        step = Decimal(lot_filter["stepSize"])
        min_qty = Decimal(lot_filter["minQty"])
        return step, min_qty

    def _extract_min_notional(self, symbol_info: Dict[str, Any]) -> Decimal:
        try:
            notional_filter = self._get_filter(symbol_info, "MIN_NOTIONAL")
        except RuntimeError:
            return Decimal("0")

        raw_value = notional_filter.get("minNotional") or notional_filter.get("notional")
        if raw_value is None:
            return Decimal("0")
        return Decimal(raw_value)

    def _extract_quote_filled(self, order: Dict[str, Any]) -> Decimal:
        for key in ("cumQuote", "cummulativeQuoteQty", "executedQuoteQty"):
            if key in order:
                return Decimal(order[key])
        return Decimal("0")

    def _wait_for_spot_fill(self, order: Dict[str, Any], retries: int = 5, delay: float = 1.0) -> Dict[str, Any]:
        order_id = order.get("orderId")
        if order_id is None:
            return order
        last = order
        for _ in range(retries):
            time.sleep(delay)
            last = self._request(
                self.spot_base_url,
                "/api/v1/order",
                params={"symbol": self.spot_symbol, "orderId": order_id},
                signed=True,
            )
            self._logger.debug(
                "Spot poll | orderId=%s | status=%s | executedQty=%s",
                order_id,
                last.get("status"),
                last.get("executedQty"),
            )
            status = last.get("status")
            if status in {"FILLED", "PARTIALLY_FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                break
        return last

    def _wait_for_futures_fill(self, order: Dict[str, Any], retries: int = 5, delay: float = 1.0) -> Dict[str, Any]:
        order_id = order.get("orderId")
        if order_id is None:
            return order
        last = order
        for _ in range(retries):
            time.sleep(delay)
            last = self._request(
                self.futures_base_url,
                "/fapi/v1/order",
                params={"symbol": self.futures_symbol, "orderId": order_id},
                signed=True,
            )
            self._logger.debug(
                "Futures poll | orderId=%s | status=%s | executedQty=%s",
                order_id,
                last.get("status"),
                last.get("executedQty"),
            )
            status = last.get("status")
            if status in {"FILLED", "PARTIALLY_FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                break
        return last

    def _get_filter(self, symbol_info: Dict[str, Any], filter_type: str) -> Dict[str, Any]:
        for flt in symbol_info.get("filters", []):
            if flt.get("filterType") == filter_type:
                return flt
        raise RuntimeError(f"Filter {filter_type} not found for symbol")

    def _request(
        self,
        base_url: str,
        path: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
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
        payload = dict(params)
        payload.setdefault("recvWindow", self.recv_window)
        payload["timestamp"] = int(time.time() * 1000)
        query = urlencode(payload, doseq=True)
        signature = hmac.new(self._api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = signature
        return payload

    def _floor_to_step(self, value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            return value
        remainder = value % step
        return (value - remainder).quantize(step, rounding=ROUND_DOWN)

    def _decimal_to_str(self, value: Decimal) -> str:
        s = format(value, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler()
    use_color = getattr(handler.stream, "isatty", lambda: False)()
    formatter = ColorFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        use_color=use_color,
    )
    handler.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="AsterDex funding fee farming helper")
    parser.add_argument(
        "--capital",
        type=str,
        default=str(DEFAULT_CAPITAL_USD),
        help="Quote currency amount (USDT) to deploy on the spot leg",
    )
    parser.add_argument(
        "--spot-symbol",
        type=str,
        default=DEFAULT_SPOT_SYMBOL,
        help="Spot trading pair for the spot leg",
    )
    parser.add_argument(
        "--futures-symbol",
        type=str,
        default=DEFAULT_FUTURES_SYMBOL,
        help="Futures contract for the hedge leg",
    )
    parser.add_argument(
        "--batch-quote",
        type=str,
        default=str(DEFAULT_BATCH_QUOTE),
        help="Quote amount (USDT) per spot order batch",
    )
    parser.add_argument(
        "--batch-delay",
        type=float,
        default=DEFAULT_BATCH_DELAY,
        help="Delay in seconds between spot batches",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        choices=[MODE_BUY_SPOT_SHORT_FUTURES, MODE_SELL_SPOT_LONG_FUTURES],
        help="Trading direction",
    )
    args = parser.parse_args()

    configure_logging(args.log_level)

    capital_usd = Decimal(args.capital)
    batch_quote = Decimal(args.batch_quote)
    bot = AsterDexFundingBot(
        capital_usd=capital_usd,
        spot_symbol=args.spot_symbol,
        futures_symbol=args.futures_symbol,
        batch_quote=batch_quote,
        batch_delay=args.batch_delay,
        mode=args.mode,
    )

    result = bot.execute()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
