#!/usr/bin/env python3
"""Delta-neutral rebalancing utilities for AsterDex."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

from .client import AsterDexClient

logger = logging.getLogger(__name__)


@dataclass
class ExposureSnapshot:
    spot_qty: Decimal
    spot_value: Decimal
    futures_qty: Decimal
    futures_value: Decimal
    mark_price: Decimal
    base_asset: str
    spot_usdt: Decimal
    futures_wallet: Decimal
    futures_side: str


def _parse_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # pylint: disable=broad-except
        return default


def _derive_base_asset(symbol_info: Dict[str, Any], symbol: str) -> str:
    if symbol_info:
        base = symbol_info.get("baseAsset") or symbol_info.get("baseSymbol")
        if base:
            return base
    if symbol.endswith("USDT"):
        return symbol[:-4]
    if symbol.endswith("USD"):
        return symbol[:-3]
    return symbol


def _get_mark_price(client: AsterDexClient, symbol: str) -> Decimal:
    try:
        data = client.get_mark_price(symbol)
        if isinstance(data, dict):
            price = data.get("markPrice") or data.get("price")
            if price is not None:
                return Decimal(str(price))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Mark price fetch failed for %s: %s", symbol, exc)
    return client.get_futures_price(symbol)


def _gather_snapshot(
    client: AsterDexClient,
    spot_symbol: str,
    futures_symbol: str,
) -> ExposureSnapshot:
    spot_info = client.get_symbol_info(spot_symbol, "spot")
    futures_info = client.get_symbol_info(futures_symbol, "futures")

    mark_price = _get_mark_price(client, futures_symbol)
    base_asset = _derive_base_asset(spot_info or futures_info, spot_symbol)

    spot_balances = client.get_spot_balance() or []
    spot_qty = Decimal("0")
    spot_usdt = Decimal("0")
    for entry in spot_balances:
        asset = entry.get("asset")
        free = _parse_decimal(entry.get("free"))
        locked = _parse_decimal(entry.get("locked"))
        if asset == base_asset:
            spot_qty = free + locked
        elif asset == "USDT":
            spot_usdt = free

    futures_positions = client.get_futures_positions() or []
    futures_qty = Decimal("0")
    futures_side = "flat"
    for pos in futures_positions:
        if pos.get("symbol") != futures_symbol:
            continue
        qty = _parse_decimal(pos.get("positionAmt"))
        if qty == 0:
            continue
        futures_qty = qty.copy_abs()
        futures_side = "short" if qty < 0 else "long"
        break

    futures_balance = client.get_futures_balance() or {}
    futures_wallet = _parse_decimal(futures_balance.get("totalWalletBalance"))

    spot_value = (spot_qty * mark_price).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    futures_value = (futures_qty * mark_price).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)

    return ExposureSnapshot(
        spot_qty=spot_qty,
        spot_value=spot_value,
        futures_qty=futures_qty,
        futures_value=futures_value,
        mark_price=mark_price,
        base_asset=base_asset,
        spot_usdt=spot_usdt,
        futures_wallet=futures_wallet,
        futures_side=futures_side,
    )


def _floor(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    remainder = value % step
    return (value - remainder).quantize(step, rounding=ROUND_DOWN)


def rebalance_delta_neutral(
    client: AsterDexClient,
    spot_symbol: str,
    futures_symbol: str,
    *,
    threshold_percent: Decimal = Decimal("5"),
    min_adjust_usd: Decimal = Decimal("10"),
) -> Dict[str, Any]:
    spot_symbol = spot_symbol.upper()
    futures_symbol = futures_symbol.upper()
    snapshot_before = _gather_snapshot(client, spot_symbol, futures_symbol)

    if snapshot_before.futures_side not in {"short", "long"}:
        return {
            "status": "skipped",
            "reason": "no futures position detected",
            "snapshot": snapshot_before.__dict__,
        }

    if snapshot_before.spot_qty <= 0:
        return {
            "status": "skipped",
            "reason": "no spot holdings detected",
            "snapshot": snapshot_before.__dict__,
        }

    avg_value = (snapshot_before.spot_value + snapshot_before.futures_value) / Decimal("2")
    if avg_value <= 0:
        return {
            "status": "skipped",
            "reason": "unable to calculate average exposure",
            "snapshot": snapshot_before.__dict__,
        }

    diff_usd = snapshot_before.spot_value - snapshot_before.futures_value
    imbalance_percent = (diff_usd.copy_abs() / avg_value) * Decimal("100")

    if imbalance_percent <= threshold_percent:
        return {
            "status": "stable",
            "reason": "exposure within threshold",
            "snapshot": snapshot_before.__dict__,
            "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
        }

    target_value = avg_value
    actions: List[Dict[str, Any]] = []

    spot_step, spot_min_qty = client.get_lot_size_info(spot_symbol, "spot")
    futures_step, futures_min_qty = client.get_lot_size_info(futures_symbol, "futures")
    futures_min_notional = client.get_min_notional(futures_symbol, "futures")

    if diff_usd > 0:
        scenario = "spot_overweight"
        spot_usd_to_sell = diff_usd
        if spot_usd_to_sell < min_adjust_usd:
            return {
                "status": "skipped",
                "reason": "difference below minimum adjustment",
                "scenario": scenario,
                "snapshot": snapshot_before.__dict__,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
            }
        spot_qty_target = spot_usd_to_sell / snapshot_before.mark_price
        spot_qty_sell = _floor(spot_qty_target, spot_step)
        if spot_qty_sell < spot_min_qty:
            return {
                "status": "skipped",
                "reason": "spot order below minimum quantity",
                "scenario": scenario,
                "snapshot": snapshot_before.__dict__,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
            }

        spot_order = client.place_spot_market_sell(spot_symbol, spot_qty_sell)
        executed_qty = _parse_decimal(spot_order.get("executedQty"))
        received_quote = _parse_decimal(spot_order.get("cummulativeQuoteQty") or spot_order.get("cumQuote"))
        actions.append({
            "type": "spot_sell",
            "requested_qty": str(spot_qty_sell),
            "executed_qty": str(executed_qty),
            "received_quote": str(received_quote),
        })

        transfer_amount = received_quote if received_quote > 0 else (spot_qty_sell * snapshot_before.mark_price)
        transfer_amount = transfer_amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if transfer_amount > 0:
            transfer = client.transfer_between_wallets("USDT", transfer_amount, "SPOT_FUTURE")
            actions.append({
                "type": "transfer_spot_to_futures",
                "amount": str(transfer_amount),
                "response": transfer,
            })

        futures_target_value = target_value
        futures_current_value = snapshot_before.futures_value
        futures_usd_to_add = futures_target_value - futures_current_value
        if futures_usd_to_add <= 0:
            futures_usd_to_add = transfer_amount
        futures_qty_add = _floor(futures_usd_to_add / snapshot_before.mark_price, futures_step)
        if futures_qty_add < futures_min_qty:
            return {
                "status": "partial",
                "reason": "futures order below minimum quantity",
                "scenario": scenario,
                "actions": actions,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
            }

        projected_notional = futures_qty_add * snapshot_before.mark_price
        if futures_min_notional > 0 and projected_notional < futures_min_notional:
            return {
                "status": "partial",
                "reason": "futures order below minimum notional",
                "scenario": scenario,
                "actions": actions,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
                "projected_notional": str(projected_notional),
            }

        futures_order = client.place_futures_market_short(futures_symbol, futures_qty_add)
        futures_executed = _parse_decimal(
            futures_order.get("executedQty") or futures_order.get("origQty")
        )
        actions.append({
            "type": "futures_add_short",
            "requested_qty": str(futures_qty_add),
            "executed_qty": str(futures_executed),
            "order": futures_order,
        })

    else:
        scenario = "futures_overweight"
        futures_usd_to_close = diff_usd.copy_abs()
        if futures_usd_to_close < min_adjust_usd:
            return {
                "status": "skipped",
                "reason": "difference below minimum adjustment",
                "scenario": scenario,
                "snapshot": snapshot_before.__dict__,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
            }
        futures_qty_target = futures_usd_to_close / snapshot_before.mark_price
        futures_qty_close = _floor(futures_qty_target, futures_step)
        if futures_qty_close < futures_min_qty:
            return {
                "status": "skipped",
                "reason": "futures order below minimum quantity",
                "scenario": scenario,
                "snapshot": snapshot_before.__dict__,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
            }

        futures_close_order = client.place_futures_market_long(futures_symbol, futures_qty_close)
        futures_executed = _parse_decimal(
            futures_close_order.get("executedQty") or futures_close_order.get("origQty")
        )
        actions.append({
            "type": "futures_close_short",
            "requested_qty": str(futures_qty_close),
            "executed_qty": str(futures_executed),
            "order": futures_close_order,
        })

        transfer_amount = (futures_qty_close * snapshot_before.mark_price).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        if transfer_amount > 0:
            transfer = client.transfer_between_wallets("USDT", transfer_amount, "FUTURE_SPOT")
            actions.append({
                "type": "transfer_futures_to_spot",
                "amount": str(transfer_amount),
                "response": transfer,
            })

        spot_usd_to_buy = target_value - snapshot_before.spot_value
        if spot_usd_to_buy <= 0:
            spot_usd_to_buy = transfer_amount
        if spot_usd_to_buy < min_adjust_usd:
            spot_usd_to_buy = transfer_amount
        spot_usd_to_buy = spot_usd_to_buy.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if spot_usd_to_buy <= 0:
            return {
                "status": "partial",
                "reason": "insufficient quote to buy spot",
                "scenario": scenario,
                "actions": actions,
                "imbalance_percent": str(imbalance_percent.quantize(Decimal("0.01"))),
            }

        spot_buy_order = client.place_spot_market_buy(spot_symbol, spot_usd_to_buy)
        executed_qty = _parse_decimal(spot_buy_order.get("executedQty"))
        actions.append({
            "type": "spot_buy",
            "quote_spent": str(spot_usd_to_buy),
            "executed_qty": str(executed_qty),
            "order": spot_buy_order,
        })

    snapshot_after = _gather_snapshot(client, spot_symbol, futures_symbol)
    new_diff = snapshot_after.spot_value - snapshot_after.futures_value
    new_imbalance_percent = (new_diff.copy_abs() / ((snapshot_after.spot_value + snapshot_after.futures_value) / Decimal("2"))) * Decimal("100") if (snapshot_after.spot_value + snapshot_after.futures_value) > 0 else Decimal("0")

    return {
        "status": "adjusted",
        "scenario": scenario,
        "actions": actions,
        "snapshot_before": snapshot_before.__dict__,
        "snapshot_after": snapshot_after.__dict__,
        "imbalance_percent_before": str(imbalance_percent.quantize(Decimal("0.01"))),
        "imbalance_percent_after": str(new_imbalance_percent.quantize(Decimal("0.01"))),
        "threshold_percent": str(threshold_percent),
    }
