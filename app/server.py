#!/usr/bin/env python3
"""Multi-DEX FastAPI server for funding-fee arbitrage bots."""

import asyncio
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .config import ConfigManager
from dexes.factory import DexFactory
from dexes.asterdex.rebalancer import rebalance_delta_neutral

logger = logging.getLogger(__name__)


def _load_env_file(env_file: Optional[str] = None) -> None:
    """Load environment variables from a .env file if present."""
    candidate = env_file or os.getenv("FUNDING_ENV_FILE", ".env")
    search_paths: List[str] = []

    if candidate:
        if os.path.isabs(candidate):
            search_paths.append(candidate)
        else:
            base_dirs = {
                os.getcwd(),
                os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(__file__)),
            }
            for base in base_dirs:
                search_paths.append(os.path.abspath(os.path.join(base, candidate)))

    for path in search_paths:
        if not os.path.isfile(path):
            continue

        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            logger.info("Loaded environment variables from %s", path)
            break
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to load environment file %s: %s", path, exc)


_load_env_file()

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Multi-DEX Funding Bot API",
    description="Manage funding-fee arbitrage bots across supported DEX integrations",
    version="2.0.0",
)

config_manager = ConfigManager()
DEFAULT_DEX = "asterdex"
DEFAULT_MODE = "buy_spot_short_futures"
VALID_MODES = {"buy_spot_short_futures", "sell_spot_long_futures"}

AUTO_REBALANCE_ENABLED = os.getenv("AUTO_REBALANCE_ENABLED", "true").lower() not in {"0", "false", "no"}
AUTO_REBALANCE_MARGIN_THRESHOLD = Decimal(os.getenv("AUTO_REBALANCE_MARGIN_THRESHOLD", "0.08"))
AUTO_REBALANCE_LEVERAGE_THRESHOLD = Decimal(os.getenv("AUTO_REBALANCE_LEVERAGE_THRESHOLD", "3"))
AUTO_REBALANCE_COOLDOWN_SECONDS = int(os.getenv("AUTO_REBALANCE_COOLDOWN_SECONDS", "300"))
AUTO_REBALANCE_THRESHOLD_PERCENT = Decimal(os.getenv("AUTO_REBALANCE_THRESHOLD_PERCENT", "5"))
AUTO_REBALANCE_MIN_ADJUST_USD = Decimal(os.getenv("AUTO_REBALANCE_MIN_ADJUST_USD", "10"))


def _get_unwind_mode(mode: str) -> Optional[str]:
    """Return the opposite trading mode used to unwind an existing position."""
    if mode == "buy_spot_short_futures":
        return "sell_spot_long_futures"
    if mode == "sell_spot_long_futures":
        return "buy_spot_short_futures"
    return None

bot_jobs: Dict[str, Dict[str, Any]] = {}
bot_results: Dict[str, Dict[str, Any]] = {}
bot_lock = threading.Lock()

# Cache for initialized DEX resources (monitor, credentials, last error)
dex_resources: Dict[str, Dict[str, Any]] = {}
dex_lock = threading.Lock()

# Latest monitoring snapshots keyed by dex
monitor_data: Dict[str, Dict[str, Any]] = {}
monitor_data_lock = threading.Lock()

monitor_interval_seconds = 30
monitor_active = True
monitor_thread: Optional[threading.Thread] = None

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class BotStartRequest(BaseModel):
    dex: Optional[str] = Field(default=None, description="DEX identifier, e.g. 'asterdex'")
    capital: str = Field(default="100", description="Capital to deploy in quote currency")
    spot_symbol: Optional[str] = Field(default=None, description="Spot trading symbol")
    futures_symbol: Optional[str] = Field(default=None, description="Futures trading symbol")
    batch_quote: str = Field(default="10", description="Quote amount per batch")
    batch_delay: float = Field(default=1.0, description="Delay between batch executions in seconds")
    mode: str = Field(default=DEFAULT_MODE, description="Trading direction mode")
    recv_window: Optional[int] = Field(default=None, description="Maintained for backward compatibility; ignored")
    api_key: Optional[str] = Field(default=None, description="Optional API key override")
    api_secret: Optional[str] = Field(default=None, description="Optional API secret override")


class BotStartResponse(BaseModel):
    job_id: str
    status: str
    message: str


class BalanceReallocateRequest(BaseModel):
    dex: Optional[str] = Field(default=None, description="DEX identifier, e.g. 'asterdex'")
    asset: str = Field(default="USDT", description="Asset to balance between spot and futures")
    tolerance: float = Field(default=1.0, ge=0.0, description="Skip transfer when imbalance is within this amount")
    max_transfer: Optional[float] = Field(default=None, gt=0.0, description="Optional cap on transfer size")


class BalanceReallocateResponse(BaseModel):
    status: str
    message: str
    asset: str
    spot_before: str
    futures_before: str
    spot_after: Optional[str] = None
    futures_after: Optional[str] = None
    transfer: Optional[Dict[str, Any]] = None


class DeltaRebalanceRequest(BaseModel):
    dex: Optional[str] = Field(default=None, description="DEX identifier, defaults to configured DEX")
    symbol: Optional[str] = Field(default=None, description="Primary trading symbol, e.g. 'ASTERUSDT'")
    threshold_percent: float = Field(default=5.0, ge=0.0, description="Rebalance trigger percentage based on exposure difference")
    min_adjust_usd: float = Field(default=10.0, ge=0.0, description="Minimum USD notional to adjust when rebalancing")


class DeltaRebalanceResponse(BaseModel):
    status: str
    scenario: Optional[str] = None
    reason: Optional[str] = None
    imbalance_percent_before: Optional[str] = None
    imbalance_percent_after: Optional[str] = None
    actions: Optional[List[Dict[str, Any]]] = None
    snapshot: Optional[Dict[str, Any]] = None
    snapshot_before: Optional[Dict[str, Any]] = None
    snapshot_after: Optional[Dict[str, Any]] = None
    threshold_percent: Optional[str] = None

    class Config:
        extra = "allow"


class BotStatus(BaseModel):
    job_id: str
    dex: str
    status: str
    config: Dict[str, str]
    created_time: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: List[BotStatus]


class StopResponse(BaseModel):
    message: str
    recommendation: str


class HealthResponse(BaseModel):
    status: str
    timestamp: str


class UnwindPositionsRequest(BaseModel):
    dex: Optional[str] = Field(default=None, description="DEX identifier, defaults to configured DEX")
    symbol: Optional[str] = Field(default=None, description="Primary trading symbol, e.g. 'ASTERUSDT'")
    spot_symbol: Optional[str] = Field(default=None, description="Override spot symbol if different from symbol")
    futures_symbol: Optional[str] = Field(default=None, description="Override futures symbol if different from symbol")
    api_key: Optional[str] = Field(default=None, description="Optional API key override")
    api_secret: Optional[str] = Field(default=None, description="Optional API secret override")


def _merge_unwind_request(
    base: Optional[UnwindPositionsRequest],
    **overrides: Optional[str],
) -> UnwindPositionsRequest:
    data: Dict[str, Any] = {}
    if base is not None:
        data.update({k: v for k, v in base.dict().items() if v not in {None, ""}})

    for key, value in overrides.items():
        if value not in {None, ""}:
            data[key] = value

    return UnwindPositionsRequest(**data)


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------
def _parse_decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid decimal for {field}: {value}")


def _normalize_dex_name(dex: Optional[str]) -> str:
    if dex:
        return dex.lower()
    cfg = config_manager.load_config()
    return (cfg.dex or DEFAULT_DEX).lower()


def _resolve_credentials(dex_name: str, overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    overrides = overrides or {}
    info = DexFactory.get_dex_info(dex_name)
    env_prefix = info["env_prefix"]

    api_key = overrides.get("api_key") or os.getenv(f"{env_prefix}_API_KEY")
    api_secret = overrides.get("api_secret") or os.getenv(f"{env_prefix}_API_SECRET")

    # Backward-compatible fallback for AsterDex defaults stored in config
    if env_prefix == "ASTERDEX":
        cfg = config_manager.load_config()
        api_key = api_key or cfg.api_key
        api_secret = api_secret or cfg.api_secret

    if not api_key or not api_secret:
        raise RuntimeError(
            f"Missing API credentials for {dex_name}. "
            f"Set {env_prefix}_API_KEY and {env_prefix}_API_SECRET or supply overrides"
        )
    return {"api_key": api_key, "api_secret": api_secret}


def _summarize_account_status(dex_name: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not snapshot or "error" in snapshot:
        return {
            "dex": dex_name,
            "error": snapshot.get("error") if isinstance(snapshot, dict) else "snapshot unavailable",
        }

    summary = snapshot.get("summary", {}) or {}
    hedging = snapshot.get("hedging", {}) or {}
    funding = snapshot.get("funding", {}) or {}
    mark_data = snapshot.get("mark_price", {}) or {}

    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    spot_holdings: List[Dict[str, Any]] = []
    for asset in summary.get("spot", {}).get("balance", []) or []:
        free = _safe_float(asset.get("free"))
        locked = _safe_float(asset.get("locked"))
        if (free or 0) > 0 or (locked or 0) > 0:
            spot_holdings.append({
                "asset": asset.get("asset", "?"),
                "free": free,
                "locked": locked,
            })

    futures_positions: List[Dict[str, Any]] = []
    for pos in summary.get("futures", {}).get("positions", []) or []:
        futures_positions.append({
            "symbol": pos.get("symbol", "?"),
            "position_amt": pos.get("positionAmt") or pos.get("position_amt"),
            "unrealized_pnl": pos.get("unRealizedProfit") or pos.get("unrealized_pnl"),
        })

    hedge_ratio = (_safe_float(hedging.get("average_efficiency")) or 0.0) * 100
    strategy_active = hedging.get("total_pairs", 0) > 0 and hedge_ratio >= 80
    strategy_status = "🟢 Active" if strategy_active else "⭕ Inactive"
    health = "HEALTHY" if 95 <= hedge_ratio <= 105 else "NEEDS_ATTENTION"

    funding_totals = funding.get("funding_totals") or {}
    funding_accumulated = _safe_float(funding_totals.get("30_days"))

    effective_rates = funding.get("effective_rates") or {}
    projections = funding.get("projections") or {}

    apy_analysis = {
        "seven_day_rate_percent": _safe_float(effective_rates.get("7_day_rate_percent")),
        "thirty_day_rate_percent": _safe_float(effective_rates.get("30_day_rate_percent")),
        "monthly_projection_usd": _safe_float(projections.get("monthly_projected")),
        "yearly_projection_usd": _safe_float(projections.get("yearly_projected")),
    }

    mark_overview: Dict[str, Any] = {}
    if isinstance(mark_data, dict):
        if "error" in mark_data:
            mark_overview["error"] = mark_data.get("error")
        else:
            mark_overview = {
                "mark_price": _safe_float(mark_data.get("mark_price") or mark_data.get("markPrice")),
                "last_funding_rate_percent": _safe_float(mark_data.get("last_funding_rate_percent")),
                "estimated_apy_percent": _safe_float(mark_data.get("estimated_apy_percent") or mark_data.get("net_estimated_apy_percent")),
                "next_funding_time": mark_data.get("next_funding_time_iso") or mark_data.get("next_funding_time"),
            }

    return {
        "dex": dex_name,
        "spot_holdings": spot_holdings,
        "futures_positions": futures_positions,
        "strategy_status": strategy_status,
        "health": health,
        "hedge_ratio_percent": hedge_ratio,
        "funding_accumulated_30d_usd": funding_accumulated,
        "apy_analysis": apy_analysis,
        "mark_price_overview": mark_overview,
    }


def _print_account_status(dex_name: str, snapshot: Dict[str, Any]) -> None:
    summary = _summarize_account_status(dex_name, snapshot)
    if not summary or summary.get("error"):
        return

    print(f"\n=== {dex_name.upper()} Account Status ===")
    spot_holdings = summary.get("spot_holdings", [])
    if spot_holdings:
        print("Spot Holdings:")
        for holding in spot_holdings:
            free = holding.get("free")
            locked = holding.get("locked")
            free_str = f"{free:.6f}" if free is not None else "0"
            if locked is not None and locked > 0:
                print(f"  {holding.get('asset', '?')}: {free_str} (locked: {locked:.6f})")
            else:
                print(f"  {holding.get('asset', '?')}: {free_str}")

    futures_positions = summary.get("futures_positions", [])
    if futures_positions:
        print("Futures Positions:")
        for pos in futures_positions:
            print(f"  {pos.get('symbol', '?')}: {pos.get('position_amt')} (PnL: ${pos.get('unrealized_pnl')})")

    print(f"Strategy: {summary.get('strategy_status')}")
    print(f"Health: {summary.get('health')}")
    print(f"Hedge Ratio: {summary.get('hedge_ratio_percent', 0):.2f}%")

    if summary.get("funding_accumulated_30d_usd") is not None:
        print(f"Funding Accumulated (30d): ${summary['funding_accumulated_30d_usd']:.4f}")

    apy = summary.get("apy_analysis", {})
    if any(value is not None for value in apy.values()):
        print("APY Analysis:")
        if apy.get("seven_day_rate_percent") is not None:
            print(f"  7d Effective Rate: {apy['seven_day_rate_percent']:.2f}%")
        if apy.get("thirty_day_rate_percent") is not None:
            print(f"  30d Effective Rate: {apy['thirty_day_rate_percent']:.2f}%")
        if apy.get("monthly_projection_usd") is not None:
            print(f"  Monthly Projection: ${apy['monthly_projection_usd']:.2f}")
        if apy.get("yearly_projection_usd") is not None:
            print(f"  Yearly Projection: ${apy['yearly_projection_usd']:.2f}")

    mark = summary.get("mark_price_overview", {})
    if mark:
        print("Mark Price Overview:")
        if mark.get("error"):
            print(f"  Mark Price: unavailable ({mark['error']})")
        else:
            if mark.get("mark_price") is not None:
                print(f"  Mark Price: {mark['mark_price']:.6f}")
            if mark.get("last_funding_rate_percent") is not None:
                print(f"  Last Funding Rate: {mark['last_funding_rate_percent']:.4f}%")
            if mark.get("estimated_apy_percent") is not None:
                print(f"  Estimated Funding APY: {mark['estimated_apy_percent']:.2f}%")
            if mark.get("next_funding_time"):
                print(f"  Next Funding: {mark['next_funding_time']}")
    print(f"=== {dex_name.upper()} Ready ===\n")

def _ensure_dex_resources(
    dex_name: str,
    credentials: Dict[str, str],
    default_symbol: Optional[str] = None,
    mark_price_interval: Optional[int] = None,
) -> None:
    with dex_lock:
        resource = dex_resources.get(dex_name)
        if resource and resource.get("monitor"):
            if default_symbol and not resource.get("default_symbol"):
                resource["default_symbol"] = default_symbol
            if mark_price_interval:
                resource["mark_price_interval"] = mark_price_interval
            resource.setdefault("auto_rebalance_cooldown", AUTO_REBALANCE_COOLDOWN_SECONDS)
            resource.setdefault("last_auto_rebalance", 0.0)
            return
        try:
            monitor = DexFactory.create_monitor(dex_name, **credentials)
            interval = mark_price_interval or monitor_interval_seconds or 60
            dex_resources[dex_name] = {
                "monitor": monitor,
                "credentials": credentials,
                "last_error": None,
                "default_symbol": default_symbol,
                "mark_price_interval": interval,
                "mark_price_last_fetch": 0.0,
                "mark_price_cache": None,
                "last_auto_rebalance": 0.0,
                "auto_rebalance_cooldown": AUTO_REBALANCE_COOLDOWN_SECONDS,
            }
            logger.info("Initialized %s monitor", dex_name)
        except Exception as exc:  # pylint: disable=broad-except
            dex_resources[dex_name] = {
                "monitor": None,
                "credentials": credentials,
                "last_error": str(exc),
                "default_symbol": default_symbol,
                "mark_price_interval": mark_price_interval or monitor_interval_seconds or 60,
            }
            raise


def _refresh_monitor_snapshot(dex_name: str) -> Dict[str, Any]:
    with dex_lock:
        resource = dex_resources.get(dex_name)
    if not resource:
        raise RuntimeError(f"DEX {dex_name} not initialized")

    monitor = resource.get("monitor")
    if not monitor:
        raise RuntimeError(resource.get("last_error") or f"Monitor unavailable for {dex_name}")

    try:
        summary = monitor.get_portfolio_summary()
        hedging = monitor.get_hedging_efficiency()
        risk = monitor.get_risk_metrics()
        pnl = monitor.get_position_pnl()
        funding = monitor.get_funding_analytics(days=30)

        mark_symbol = resource.get("default_symbol") or "ASTERUSDT"
        mark_interval = resource.get("mark_price_interval", monitor_interval_seconds or 60)

        now_ts = time.time()
        mark_price = resource.get("mark_price_cache")
        last_fetch = resource.get("mark_price_last_fetch", 0.0)

        if mark_price is None or now_ts - last_fetch >= mark_interval:
            try:
                mark_price = monitor.get_mark_price_context(symbol=mark_symbol)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Mark price context fetch failed for %s: %s", dex_name, exc)
                mark_price = {"error": str(exc), "timestamp": datetime.now().isoformat()}

            with dex_lock:
                resource["mark_price_cache"] = mark_price
                resource["mark_price_last_fetch"] = now_ts

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "hedging": hedging,
            "risk": risk,
            "pnl": pnl,
            "funding": funding,
            "mark_price": mark_price,
        }
        snapshot["account_status"] = _summarize_account_status(dex_name, snapshot)
        with monitor_data_lock:
            monitor_data[dex_name] = snapshot
        _log_snapshot(dex_name, snapshot)
        _print_account_status(dex_name, snapshot)
        resource["last_error"] = None
        try:
            _maybe_auto_rebalance(dex_name, resource, snapshot)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Auto rebalance evaluation failed for %s: %s", dex_name.upper(), exc)
        return snapshot
    except Exception as exc:  # pylint: disable=broad-except
        error_snapshot = {
            "timestamp": datetime.now().isoformat(),
            "error": str(exc),
        }
        with monitor_data_lock:
            monitor_data[dex_name] = error_snapshot
        resource["last_error"] = str(exc)
        raise


def _start_monitor_thread() -> None:
    global monitor_thread  # noqa: PLW0603
    if monitor_thread and monitor_thread.is_alive():
        return

    def _loop() -> None:
        while monitor_active:
            with dex_lock:
                tracked = list(dex_resources.keys())
            for dex_name in tracked:
                try:
                    _refresh_monitor_snapshot(dex_name)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Monitor update failed for %s: %s", dex_name, exc)
            time.sleep(max(5, monitor_interval_seconds))

    monitor_thread = threading.Thread(target=_loop, name="dex-monitor", daemon=True)
    monitor_thread.start()


def _format_currency(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:  # pylint: disable=broad-except
        return "$0.00"


def _format_percentage(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:  # pylint: disable=broad-except
        return "0.00%"


def _log_snapshot(dex_name: str, snapshot: Dict[str, Any]) -> None:
    """Emit a concise log line summarizing the latest snapshot."""
    try:
        if not snapshot:
            return

        if "error" in snapshot:
            logger.warning("%s snapshot error: %s", dex_name.upper(), snapshot["error"])
            return

        summary = snapshot.get("summary", {})
        portfolio = summary.get("portfolio", {})
        pnl = snapshot.get("pnl", {})
        funding = snapshot.get("funding", {})
        funding_totals = funding.get("funding_totals", {})
        mark = snapshot.get("mark_price", {}) or {}

        est_apy = mark.get("estimated_apy_percent")
        last_rate = mark.get("last_funding_rate_percent")
        next_funding = mark.get("next_funding_time_iso") or mark.get("next_funding_time")

        logger.info(
            "Snapshot %s | Value %s | PnL %s | Funding30d %s | APY %s | LastRate %s | Next %s",
            dex_name.upper(),
            _format_currency(portfolio.get("total_usd", 0)),
            _format_currency(pnl.get("total_unrealized_pnl", 0)),
            _format_currency(funding_totals.get("30_days", 0)),
            f"{float(est_apy):.2f}%" if est_apy is not None else "n/a",
            f"{float(last_rate):.4f}%" if last_rate is not None else "n/a",
            next_funding or "n/a",
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to log snapshot for %s: %s", dex_name, exc)


def _to_decimal_or_none(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _has_active_futures_position(snapshot: Dict[str, Any]) -> bool:
    summary = snapshot.get("summary") or {}
    futures = summary.get("futures") or {}
    positions = futures.get("positions") or []

    if isinstance(positions, dict):
        positions = positions.get("positions", [])

    for pos in positions:
        qty = pos.get("positionAmt") or pos.get("position_amt") or pos.get("qty")
        amount = _to_decimal_or_none(qty)
        if amount is not None and amount != 0:
            return True
    return False


def _assess_liquidation_risk(snapshot: Dict[str, Any]) -> Tuple[bool, str, Dict[str, str]]:
    if not _has_active_futures_position(snapshot):
        return False, "no_active_positions", {}

    risk = snapshot.get("risk") or {}
    margin_ratio = _to_decimal_or_none(risk.get("margin_ratio"))
    leverage = _to_decimal_or_none(risk.get("effective_leverage"))
    total_notional = _to_decimal_or_none(risk.get("total_notional_exposure"))

    metrics: Dict[str, str] = {}
    if margin_ratio is not None:
        metrics["margin_ratio"] = str(margin_ratio)
    if leverage is not None:
        metrics["effective_leverage"] = str(leverage)
    if total_notional is not None:
        metrics["total_notional_exposure"] = str(total_notional)

    if total_notional is None or total_notional <= 0:
        return False, "no_notional_exposure", metrics

    if margin_ratio is not None and margin_ratio <= AUTO_REBALANCE_MARGIN_THRESHOLD:
        return True, f"margin ratio {margin_ratio}", metrics

    if leverage is not None and leverage >= AUTO_REBALANCE_LEVERAGE_THRESHOLD:
        return True, f"effective leverage {leverage}", metrics

    return False, "within_limits", metrics


def _maybe_auto_rebalance(dex_name: str, resource: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    if not AUTO_REBALANCE_ENABLED:
        return

    if dex_name.lower() != "asterdex":
        return

    monitor = resource.get("monitor")
    if not monitor or not hasattr(monitor, "dex"):
        return

    should_rebalance, reason, metrics = _assess_liquidation_risk(snapshot)
    if not should_rebalance:
        return

    now_ts = time.time()
    cooldown = resource.get("auto_rebalance_cooldown", AUTO_REBALANCE_COOLDOWN_SECONDS)
    last_ts = resource.get("last_auto_rebalance", 0.0)
    if last_ts and now_ts - last_ts < cooldown:
        logger.debug(
            "%s auto-rebalance skipped due to cooldown (remaining=%ss)",
            dex_name.upper(),
            int(cooldown - (now_ts - last_ts)),
        )
        return

    cfg = config_manager.load_config()
    spot_symbol = (resource.get("default_symbol") or cfg.spot_symbol or "ASTERUSDT").upper()
    futures_symbol = (cfg.futures_symbol or spot_symbol).upper()

    try:
        result = rebalance_delta_neutral(
            monitor.dex,
            spot_symbol,
            futures_symbol,
            threshold_percent=AUTO_REBALANCE_THRESHOLD_PERCENT,
            min_adjust_usd=AUTO_REBALANCE_MIN_ADJUST_USD,
        )
        logger.warning(
            "Auto delta rebalance triggered for %s due to %s | status=%s | metrics=%s",
            dex_name.upper(),
            reason,
            result.get("status"),
            metrics,
        )
        resource["last_auto_rebalance"] = now_ts
        resource["last_auto_rebalance_reason"] = reason
        resource["last_auto_rebalance_result"] = result
    except Exception as exc:  # pylint: disable=broad-except
        resource["last_auto_rebalance"] = now_ts
        resource["last_auto_rebalance_error"] = str(exc)
        logger.error("Auto delta rebalance failed for %s: %s", dex_name.upper(), exc)

def _build_simple_report(dex_name: str, snapshot: Dict[str, Any]) -> str:
    if "error" in snapshot:
        return (
            f"{dex_name.upper()} FUNDING BOT STATUS:\n"
            f"Status: ERROR - {snapshot['error']}\n"
            f"Timestamp: {snapshot.get('timestamp', 'n/a')}\n"
        )

    summary = snapshot.get("summary", {})
    hedging = snapshot.get("hedging", {})
    pnl = snapshot.get("pnl", {})
    funding = snapshot.get("funding", {})

    portfolio = summary.get("portfolio", {})
    spot = summary.get("spot", {})
    futures = summary.get("futures", {})

    hedge_ratio = float(hedging.get("average_efficiency", 0)) * 100
    is_active = hedging.get("total_pairs", 0) > 0 and hedge_ratio >= 80
    health = "HEALTHY" if 95 <= hedge_ratio <= 105 else "NEEDS_ATTENTION"

    pnltotal = pnl.get("total_unrealized_pnl", "0")
    funding_totals = funding.get("funding_totals", {})
    daily_rates = funding.get("effective_rates", {})

    lines = [f"{dex_name.upper()} FUNDING BOT STATUS:"]
    lines.append(f"Strategy: {'🟢' if is_active else '⭕'} {'Active' if is_active else 'Inactive'}")
    lines.append(f"Health: {health}")
    lines.append(f"Hedge Ratio: {hedge_ratio:.2f}%")
    lines.append("")
    lines.append("PORTFOLIO:")
    lines.append(f"Total Value: {_format_currency(portfolio.get('total_usd', 0))}")
    lines.append(f"Spot: {_format_currency(spot.get('total_usd', 0))}")
    lines.append(f"Futures: {_format_currency(futures.get('total_usd', 0))}")
    lines.append("")
    lines.append("POSITIONS:")
    lines.append(f"Unrealized PnL: {('🟢' if float(pnltotal) >= 0 else '🔴')} {_format_currency(pnltotal)}")
    lines.append("")
    lines.append("FUNDING:")
    lines.append(f"7d Total: {_format_currency(funding_totals.get('7_days', 0))}")
    lines.append(f"30d Total: {_format_currency(funding_totals.get('30_days', 0))}")
    lines.append(f"7d Effective Rate: {_format_percentage(daily_rates.get('7_day_rate_percent', 0)/100 if daily_rates else 0)}")
    lines.append(f"30d Effective Rate: {_format_percentage(daily_rates.get('30_day_rate_percent', 0)/100 if daily_rates else 0)}")
    lines.append("")
    lines.append(f"Timestamp: {snapshot.get('timestamp')}")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Bot execution helper
# -----------------------------------------------------------------------------
class BotRunner:
    def __init__(self, job_id: str, dex_name: str, bot_kwargs: Dict[str, Any], credentials: Dict[str, str]):
        self.job_id = job_id
        self.dex_name = dex_name
        self.bot_kwargs = bot_kwargs
        self.credentials = credentials

    def run(self) -> None:
        try:
            with bot_lock:
                bot_jobs[self.job_id]["status"] = "running"
                bot_jobs[self.job_id]["start_time"] = datetime.now().isoformat()

            bot = DexFactory.create_funding_bot(
                self.dex_name,
                self.bot_kwargs["capital_usd"],
                api_key=self.credentials["api_key"],
                api_secret=self.credentials["api_secret"],
                spot_symbol=self.bot_kwargs["spot_symbol"],
                futures_symbol=self.bot_kwargs["futures_symbol"],
                batch_quote=self.bot_kwargs["batch_quote"],
                batch_delay=self.bot_kwargs["batch_delay"],
                mode=self.bot_kwargs["mode"],
            )

            result = bot.execute_strategy()

            with bot_lock:
                bot_jobs[self.job_id]["status"] = "completed"
                bot_jobs[self.job_id]["end_time"] = datetime.now().isoformat()
                bot_results[self.job_id] = result

            try:
                _refresh_monitor_snapshot(self.dex_name)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Snapshot refresh failed after job %s: %s", self.job_id, exc)

            logger.info("Bot job %s completed successfully", self.job_id)

        except Exception as exc:  # pylint: disable=broad-except
            with bot_lock:
                bot_jobs[self.job_id]["status"] = "failed"
                bot_jobs[self.job_id]["error"] = str(exc)
                bot_jobs[self.job_id]["end_time"] = datetime.now().isoformat()
            logger.error("Bot job %s failed: %s", self.job_id, exc)


def _run_bot(job_id: str, dex_name: str, bot_kwargs: Dict[str, Any], credentials: Dict[str, str]) -> None:
    runner = BotRunner(job_id, dex_name, bot_kwargs, credentials)
    runner.run()


# -----------------------------------------------------------------------------
# FastAPI lifecycle events
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event() -> None:
    global monitor_interval_seconds  # noqa: PLW0603

    logging.basicConfig(level=os.getenv("FUNDING_LOG_LEVEL", "INFO"))
    logger.info("Starting Multi-DEX Funding Bot API server")

    cfg = config_manager.load_config()
    monitor_interval_seconds = int(getattr(cfg, "monitor_interval", 30) or 30)
    default_symbol = (getattr(cfg, "spot_symbol", None) or "ASTERUSDT").upper()

    supported = DexFactory.list_supported_dexes()
    logger.info("Supported DEXes: %s", supported)

    for dex_name in supported:
        try:
            credentials = _resolve_credentials(dex_name)
        except RuntimeError as exc:
            logger.warning("Skipping %s initialization: %s", dex_name, exc)
            continue

        try:
            _ensure_dex_resources(
                dex_name,
                credentials,
                default_symbol=default_symbol,
                mark_price_interval=max(60, monitor_interval_seconds),
            )
            snapshot = _refresh_monitor_snapshot(dex_name)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Initial snapshot failed for %s: %s", dex_name, exc)
            continue

        _print_account_status(dex_name, snapshot)

    if dex_resources:
        _start_monitor_thread()
        logger.info("Background monitoring started (interval=%ss)", monitor_interval_seconds)
    else:
        logger.warning("No DEX monitors initialized; monitoring endpoints will be unavailable")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global monitor_active  # noqa: PLW0603
    monitor_active = False
    logger.info("Shutting down Multi-DEX Funding Bot API server")


# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------
@app.get("/", response_model=Dict[str, Any])
async def root() -> Dict[str, Any]:
    return {
        "name": "Multi-DEX Funding Bot API",
        "version": "2.0.0",
        "docs": "/docs",
        "supported_dexes": DexFactory.list_supported_dexes(),
    }


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy", timestamp=datetime.now().isoformat())


@app.get("/dexes", response_model=Dict[str, List[str]])
async def list_dexes() -> Dict[str, List[str]]:
    return {"supported": DexFactory.list_supported_dexes()}


@app.get("/dexes/{dex_name}", response_model=Dict[str, Any])
async def dex_info(dex_name: str) -> Dict[str, Any]:
    try:
        info = DexFactory.get_dex_info(dex_name.lower())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "name": info["name"],
        "env_prefix": info["env_prefix"],
        "required_env_vars": info["required_env_vars"],
        "client_class": info["client_class"],
        "bot_class": info["bot_class"],
        "monitor_class": info["monitor_class"],
    }


@app.post("/start", response_model=BotStartResponse)
async def start_bot(
    background_tasks: BackgroundTasks,
    request: BotStartRequest = Body(default_factory=BotStartRequest),
) -> BotStartResponse:
    dex_name = _normalize_dex_name(request.dex)
    if dex_name not in DexFactory.list_supported_dexes():
        raise HTTPException(status_code=400, detail=f"Unsupported DEX '{dex_name}'")

    capital_usd = _parse_decimal(request.capital, "capital")
    batch_quote = _parse_decimal(request.batch_quote, "batch_quote")

    if capital_usd <= 0 or batch_quote <= 0:
        raise HTTPException(status_code=400, detail="Capital and batch quote must be positive")

    cfg = config_manager.load_config()
    spot_symbol = (request.spot_symbol or cfg.spot_symbol or "ASTERUSDT").upper()
    futures_symbol = (request.futures_symbol or cfg.futures_symbol or "ASTERUSDT").upper()

    mode = request.mode or DEFAULT_MODE
    if dex_name == "asterdex" and mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode for {dex_name}: {mode}")

    override_credentials = {}
    if request.api_key:
        override_credentials["api_key"] = request.api_key
    if request.api_secret:
        override_credentials["api_secret"] = request.api_secret

    try:
        credentials = _resolve_credentials(dex_name, override_credentials)
        _ensure_dex_resources(
            dex_name,
            credentials,
            default_symbol=spot_symbol,
            mark_price_interval=max(60, monitor_interval_seconds),
        )
        with dex_lock:
            if dex_name in dex_resources:
                dex_resources[dex_name]["default_symbol"] = spot_symbol
                dex_resources[dex_name]["mark_price_interval"] = max(
                    60, monitor_interval_seconds
                )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    bot_kwargs = {
        "capital_usd": capital_usd,
        "spot_symbol": spot_symbol,
        "futures_symbol": futures_symbol,
        "batch_quote": batch_quote,
        "batch_delay": float(request.batch_delay),
        "mode": mode,
    }

    job_id = str(uuid.uuid4())
    job_summary = {
        "job_id": job_id,
        "dex": dex_name,
        "status": "pending",
        "config": {
            "capital_usd": str(capital_usd),
            "spot_symbol": spot_symbol,
            "futures_symbol": futures_symbol,
            "batch_quote": str(batch_quote),
            "batch_delay": str(request.batch_delay),
            "mode": mode,
        },
        "created_time": datetime.now().isoformat(),
        "start_time": None,
        "end_time": None,
        "error": None,
    }

    with bot_lock:
        bot_jobs[job_id] = job_summary

    background_tasks.add_task(_run_bot, job_id, dex_name, bot_kwargs, credentials)

    return BotStartResponse(job_id=job_id, status="started", message="Bot started successfully")


@app.get("/status/{job_id}", response_model=BotStatus)
async def get_status(job_id: str) -> BotStatus:
    with bot_lock:
        job = bot_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found")
    return BotStatus(**job)


@app.get("/jobs", response_model=JobListResponse)
async def list_jobs() -> JobListResponse:
    with bot_lock:
        jobs = [BotStatus(**job) for job in bot_jobs.values()]
    return JobListResponse(jobs=jobs)


@app.get("/result/{job_id}")
async def get_result(job_id: str) -> Dict[str, Any]:
    with bot_lock:
        job = bot_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job ID not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=400, detail=f"Job not completed (status={job['status']})")
        result = bot_results.get(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return result


@app.post("/stop/{job_id}", response_model=StopResponse)
async def stop_bot(job_id: str) -> StopResponse:
    with bot_lock:
        job = bot_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job ID not found")
        if job["status"] not in {"pending", "running"}:
            raise HTTPException(status_code=400, detail=f"Cannot stop job in status {job['status']}")

    return StopResponse(
        message="Stop requested, but trading bot cannot be safely interrupted once submitted",
        recommendation="Allow the current job to finish, then run the opposite mode to unwind positions",
    )


def _perform_unwind(  # noqa: PLR0915
    dex_name: str,
    spot_symbol: str,
    futures_symbol: str,
    credentials: Dict[str, str],
) -> Dict[str, Any]:
    if dex_name != "asterdex":
        raise HTTPException(status_code=400, detail="Automatic unwind currently supports only AsterDex")

    client = DexFactory.create_client(
        dex_name,
        api_key=credentials["api_key"],
        api_secret=credentials["api_secret"],
    )

    spot_info = client.get_symbol_info(spot_symbol, "spot")
    futures_info = client.get_symbol_info(futures_symbol, "futures")
    if not spot_info or not futures_info:
        raise HTTPException(status_code=400, detail=f"Unable to load symbol metadata for {spot_symbol}")

    base_asset = spot_info.get("baseAsset") or spot_symbol.replace("USDT", "")

    spot_balance = client.get_spot_balance()
    base_balance = Decimal("0")
    for asset in spot_balance:
        if asset.get("asset") == base_asset:
            free = Decimal(str(asset.get("free", "0")))
            locked = Decimal(str(asset.get("locked", "0")))
            base_balance = free + locked
            break

    futures_positions = client.get_futures_positions()
    futures_amt = Decimal("0")
    futures_side = None
    for pos in futures_positions:
        if pos.get("symbol") == futures_symbol:
            amt = Decimal(str(pos.get("positionAmt", "0")))
            if amt != 0:
                futures_amt = abs(amt)
                futures_side = "short" if amt < 0 else "long"
            break

    if base_balance <= 0 and futures_amt <= 0:
        return {
            "status": "noop",
            "message": f"No open positions detected for {spot_symbol}",
            "spot_balance": "0",
            "futures_position": "0",
        }

    response: Dict[str, Any] = {
        "status": "in_progress",
        "spot_symbol": spot_symbol,
        "futures_symbol": futures_symbol,
        "base_asset": base_asset,
        "actions": [],
    }

    # Handle spot unwind
    if base_balance > 0:
        spot_step, spot_min_qty = client.get_lot_size_info(spot_symbol, "spot")
        sell_qty = client._floor_to_step(base_balance, spot_step)

        if sell_qty <= 0:
            raise HTTPException(status_code=400, detail=f"Spot balance {base_balance} is below tradable step size {spot_step}")
        if sell_qty < spot_min_qty:
            raise HTTPException(status_code=400, detail=f"Spot balance {base_balance} below minimum quantity {spot_min_qty}")

        spot_order = client.place_spot_market_sell(spot_symbol, sell_qty)
        response["actions"].append({
            "type": "spot_sell",
            "quantity": client._decimal_to_str(sell_qty),
            "order": spot_order,
        })

    # Handle futures unwind
    if futures_amt > 0 and futures_side:
        futures_step, futures_min_qty = client.get_lot_size_info(futures_symbol, "futures")
        futures_qty = client._floor_to_step(futures_amt, futures_step)

        if futures_qty <= 0:
            raise HTTPException(status_code=400, detail=f"Futures position {futures_amt} is below tradable step size {futures_step}")
        if futures_qty < futures_min_qty:
            raise HTTPException(status_code=400, detail=f"Futures position {futures_amt} below minimum quantity {futures_min_qty}")

        futures_price = client.get_futures_price(futures_symbol)
        futures_notional = futures_qty * futures_price
        futures_min_notional = client.get_min_notional(futures_symbol, "futures")
        if futures_min_notional > 0 and futures_notional < futures_min_notional:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Futures position notional {futures_notional} is below minimum {futures_min_notional}. "
                    "Increase position size before attempting to unwind."
                ),
            )

        if futures_side == "short":
            futures_order = client.place_futures_market_long(futures_symbol, futures_qty)
            action = "futures_buy"
        else:
            futures_order = client.place_futures_market_short(futures_symbol, futures_qty)
            action = "futures_sell"

        response["actions"].append({
            "type": action,
            "quantity": client._decimal_to_str(futures_qty),
            "order": futures_order,
        })

    response["status"] = "completed"
    return response


async def _execute_unwind(request: UnwindPositionsRequest) -> Dict[str, Any]:
    dex_name = _normalize_dex_name(request.dex)
    symbol = request.symbol or request.spot_symbol or request.futures_symbol
    if not symbol:
        cfg = config_manager.load_config()
        symbol = getattr(cfg, "spot_symbol", "ASTERUSDT")

    spot_symbol = (request.spot_symbol or symbol).upper()
    futures_symbol = (request.futures_symbol or symbol).upper()

    try:
        info = DexFactory.get_dex_info(dex_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    env_prefix = info.get("env_prefix", "ASTERDEX")
    overrides = {
        "api_key": request.api_key or os.getenv(f"{env_prefix}_API_KEY"),
        "api_secret": request.api_secret or os.getenv(f"{env_prefix}_API_SECRET"),
    }
    overrides = {key: value for key, value in overrides.items() if value}

    try:
        credentials = _resolve_credentials(dex_name, overrides)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = await asyncio.to_thread(
            _perform_unwind,
            dex_name,
            spot_symbol,
            futures_symbol,
            credentials,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Unwind operation failed for %s: %s", spot_symbol, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        _refresh_monitor_snapshot(dex_name)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Snapshot refresh failed after unwind for %s: %s", dex_name, exc)

    return result


@app.post(
    "/unwind",
    response_model=Dict[str, Any],
    summary="Unwind positions",
    description=(
        "Close both spot and futures positions for a symbol. "
        "To issue the minimal call, use: \n"
        "`curl -X POST http://localhost:8000/unwind/ASTERUSDT -H 'Content-Type: application/json' -d '{}'`"
    ),
)
async def unwind_positions(
    request: Optional[UnwindPositionsRequest] = Body(default=None, example={}),
    dex: Optional[str] = None,
    symbol: Optional[str] = None,
    spot_symbol: Optional[str] = None,
    futures_symbol: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> Dict[str, Any]:
    combined = _merge_unwind_request(
        request,
        dex=dex,
        symbol=symbol,
        spot_symbol=spot_symbol,
        futures_symbol=futures_symbol,
        api_key=api_key,
        api_secret=api_secret,
    )
    return await _execute_unwind(combined)


@app.post(
    "/unwind/{path_symbol}",
    response_model=Dict[str, Any],
    summary="Unwind positions by symbol",
    description=(
        "Convenience endpoint for closing the book on a specific symbol via the path parameter. "
        "Example: `curl -X POST http://localhost:8000/unwind/ASTERUSDT -H 'Content-Type: application/json' -d '{}'`."
    ),
)
async def unwind_positions_by_symbol(
    path_symbol: str,
    request: Optional[UnwindPositionsRequest] = Body(default=None, example={}),
    dex: Optional[str] = None,
    spot_symbol: Optional[str] = None,
    futures_symbol: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> Dict[str, Any]:
    combined = _merge_unwind_request(
        request,
        symbol=path_symbol,
        dex=dex,
        spot_symbol=spot_symbol,
        futures_symbol=futures_symbol,
        api_key=api_key,
        api_secret=api_secret,
    )
    return await _execute_unwind(combined)


@app.post("/jobs/{job_id}/unwind", response_model=BotStartResponse)
async def unwind_bot(job_id: str, background_tasks: BackgroundTasks) -> BotStartResponse:
    with bot_lock:
        original_job = bot_jobs.get(job_id)

    if not original_job:
        raise HTTPException(status_code=404, detail="Job ID not found")

    original_status = original_job.get("status")
    if original_status == "running":
        raise HTTPException(status_code=400, detail="Cannot unwind while the original job is running")

    dex_name = original_job.get("dex")
    if not dex_name:
        raise HTTPException(status_code=500, detail="Original job missing DEX information")

    original_config = original_job.get("config") or {}
    original_mode = original_config.get("mode", DEFAULT_MODE)
    unwind_mode = _get_unwind_mode(original_mode)

    if not unwind_mode:
        raise HTTPException(status_code=400, detail=f"Unsupported mode '{original_mode}' for unwind")

    capital_usd = _parse_decimal(original_config.get("capital_usd", "0"), "capital_usd")
    batch_quote = _parse_decimal(original_config.get("batch_quote", "0"), "batch_quote")
    if capital_usd <= 0 or batch_quote <= 0:
        raise HTTPException(status_code=400, detail="Original job configuration lacks valid capital or batch quote")

    spot_symbol = original_config.get("spot_symbol") or "ASTERUSDT"
    futures_symbol = original_config.get("futures_symbol") or spot_symbol
    try:
        batch_delay = float(original_config.get("batch_delay", 1.0))
    except (TypeError, ValueError):
        batch_delay = 1.0

    try:
        credentials = _resolve_credentials(dex_name)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    unwind_job_id = str(uuid.uuid4())
    created_time = datetime.now().isoformat()
    bot_kwargs = {
        "capital_usd": capital_usd,
        "spot_symbol": spot_symbol,
        "futures_symbol": futures_symbol,
        "batch_quote": batch_quote,
        "batch_delay": batch_delay,
        "mode": unwind_mode,
    }

    unwind_config = {
        "capital_usd": str(capital_usd),
        "spot_symbol": spot_symbol,
        "futures_symbol": futures_symbol,
        "batch_quote": str(batch_quote),
        "batch_delay": str(batch_delay),
        "mode": unwind_mode,
        "parent_job_id": job_id,
    }

    unwind_summary = {
        "job_id": unwind_job_id,
        "dex": dex_name,
        "status": "pending",
        "config": unwind_config,
        "created_time": created_time,
        "start_time": None,
        "end_time": None,
        "error": None,
        "parent_job_id": job_id,
        "job_type": "unwind",
    }

    with bot_lock:
        bot_jobs[unwind_job_id] = unwind_summary

    background_tasks.add_task(_run_bot, unwind_job_id, dex_name, bot_kwargs, credentials)

    return BotStartResponse(
        job_id=unwind_job_id,
        status="started",
        message="Unwind job scheduled; positions will be closed using the opposite mode",
    )


@app.get("/monitor/{dex_name}")
async def get_monitor_snapshot(dex_name: str) -> Dict[str, Any]:
    dex_key = dex_name.lower()

    if dex_key not in DexFactory.list_supported_dexes():
        raise HTTPException(status_code=404, detail=f"Unsupported DEX '{dex_key}'")

    try:
        with dex_lock:
            resource = dex_resources.get(dex_key)
        if not resource or not resource.get("monitor"):
            credentials = _resolve_credentials(dex_key)
            _ensure_dex_resources(dex_key, credentials)
            _refresh_monitor_snapshot(dex_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    with monitor_data_lock:
        snapshot = monitor_data.get(dex_key)

    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No monitoring data for {dex_key}")
    return snapshot


@app.post("/balance/reallocate", response_model=BalanceReallocateResponse)
async def rebalance_wallets(request: BalanceReallocateRequest) -> BalanceReallocateResponse:
    dex_name = _normalize_dex_name(request.dex)
    if dex_name not in DexFactory.list_supported_dexes():
        raise HTTPException(status_code=400, detail=f"Unsupported DEX '{dex_name}'")

    asset = request.asset.upper()
    tolerance = Decimal(str(request.tolerance))
    max_transfer = Decimal(str(request.max_transfer)) if request.max_transfer else None

    try:
        credentials = _resolve_credentials(dex_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    client = DexFactory.create_client(dex_name, **credentials)

    def _to_decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return Decimal("0")

    spot_balance = client.get_spot_balance() or []
    futures_balance = client.get_futures_balance() or {}

    spot_entry = next((item for item in spot_balance if item.get("asset") == asset), None)
    spot_free = _to_decimal(spot_entry.get("free")) if spot_entry else Decimal("0")

    futures_available = Decimal("0")
    if isinstance(futures_balance, dict):
        futures_available = max(
            futures_available,
            _to_decimal(futures_balance.get("availableBalance")),
            _to_decimal(futures_balance.get("maxWithdrawAmount")),
            _to_decimal(futures_balance.get("totalWalletBalance")),
            _to_decimal(futures_balance.get("totalMarginBalance")),
        )
        for entry in futures_balance.get("assets", []) or []:
            if entry.get("asset") == asset:
                futures_available = max(
                    futures_available,
                    _to_decimal(entry.get("availableBalance")),
                    _to_decimal(entry.get("maxWithdrawAmount")),
                    _to_decimal(entry.get("walletBalance")),
                )
                break
    elif isinstance(futures_balance, list):
        for entry in futures_balance:
            if entry.get("asset") == asset:
                futures_available = max(
                    futures_available,
                    _to_decimal(entry.get("availableBalance")),
                    _to_decimal(entry.get("maxWithdrawAmount")),
                    _to_decimal(entry.get("walletBalance")),
                    _to_decimal(entry.get("balance")),
                )

    total = spot_free + futures_available
    if total <= 0:
        return BalanceReallocateResponse(
            status="skipped",
            message="No funds available to rebalance",
            asset=asset,
            spot_before=str(spot_free),
            futures_before=str(futures_available),
        )

    target = (total / Decimal("2")).quantize(Decimal("0.0001"))
    imbalance = spot_free - target

    if imbalance.copy_abs() <= tolerance:
        return BalanceReallocateResponse(
            status="skipped",
            message="Balances already within tolerance",
            asset=asset,
            spot_before=str(spot_free),
            futures_before=str(futures_available),
        )

    if max_transfer is not None:
        transfer_amount = min(imbalance.copy_abs(), max_transfer)
    else:
        transfer_amount = imbalance.copy_abs()

    if transfer_amount <= 0:
        return BalanceReallocateResponse(
            status="skipped",
            message="Calculated transfer amount is zero",
            asset=asset,
            spot_before=str(spot_free),
            futures_before=str(futures_available),
        )

    if imbalance > 0:
        direction = "SPOT_FUTURE"
        transferable = spot_free - target
    else:
        direction = "FUTURE_SPOT"
        transferable = futures_available - target

    if transferable <= Decimal("0"):
        return BalanceReallocateResponse(
            status="skipped",
            message="Source balance insufficient to rebalance",
            asset=asset,
            spot_before=str(spot_free),
            futures_before=str(futures_available),
        )

    transfer_amount = min(transfer_amount, transferable)
    transfer_amount = transfer_amount.quantize(Decimal("0.0001"))
    if transfer_amount <= Decimal("0"):
        return BalanceReallocateResponse(
            status="skipped",
            message="Transfer amount below precision",
            asset=asset,
            spot_before=str(spot_free),
            futures_before=str(futures_available),
        )

    try:
        transfer_response = client.transfer_between_wallets(
            asset=asset,
            amount=transfer_amount,
            direction=direction,
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=f"Transfer failed: {exc}") from exc

    spot_after_balance = client.get_spot_balance() or []
    futures_after_balance = client.get_futures_balance() or {}

    spot_after_entry = next((item for item in spot_after_balance if item.get("asset") == asset), None)
    spot_after = _to_decimal(spot_after_entry.get("free")) if spot_after_entry else Decimal("0")

    futures_after = Decimal("0")
    if isinstance(futures_after_balance, dict):
        futures_after = max(
            futures_after,
            _to_decimal(futures_after_balance.get("availableBalance")),
            _to_decimal(futures_after_balance.get("totalWalletBalance")),
        )
        for entry in futures_after_balance.get("assets", []) or []:
            if entry.get("asset") == asset:
                futures_after = max(
                    futures_after,
                    _to_decimal(entry.get("availableBalance")),
                    _to_decimal(entry.get("walletBalance")),
                )
                break
    elif isinstance(futures_after_balance, list):
        for entry in futures_after_balance:
            if entry.get("asset") == asset:
                futures_after = max(
                    futures_after,
                    _to_decimal(entry.get("availableBalance")),
                    _to_decimal(entry.get("walletBalance")),
                )

    return BalanceReallocateResponse(
        status="transferred",
        message=f"Moved {transfer_amount} {asset} via {direction}",
        asset=asset,
        spot_before=str(spot_free),
        futures_before=str(futures_available),
        spot_after=str(spot_after),
        futures_after=str(futures_after),
        transfer={
            "direction": direction,
            "amount": str(transfer_amount),
            "response": transfer_response,
        },
    )


@app.post("/rebalance/delta", response_model=DeltaRebalanceResponse)
async def rebalance_delta(request: DeltaRebalanceRequest) -> DeltaRebalanceResponse:
    dex_name = _normalize_dex_name(request.dex)

    if dex_name != "asterdex":
        raise HTTPException(status_code=400, detail=f"Delta-neutral rebalance currently supports only AsterDex (requested '{dex_name}')")

    cfg = config_manager.load_config()
    spot_symbol = (request.symbol or cfg.spot_symbol or "ASTERUSDT").upper()
    futures_symbol = (cfg.futures_symbol or spot_symbol).upper()

    try:
        threshold = Decimal(str(request.threshold_percent))
        min_adjust = Decimal(str(request.min_adjust_usd))
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=400, detail="Invalid threshold or minimum adjustment value")

    try:
        credentials = _resolve_credentials(dex_name)
        client = DexFactory.create_client(
            dex_name,
            api_key=credentials["api_key"],
            api_secret=credentials["api_secret"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = rebalance_delta_neutral(
        client,
        spot_symbol,
        futures_symbol,
        threshold_percent=threshold,
        min_adjust_usd=min_adjust,
    )

    result.setdefault("threshold_percent", str(threshold))
    if "imbalance_percent" in result and "imbalance_percent_before" not in result:
        result["imbalance_percent_before"] = result["imbalance_percent"]

    return DeltaRebalanceResponse(**result)


@app.get("/monitor/{dex_name}/simple", response_class=PlainTextResponse)
async def get_monitor_simple(dex_name: str) -> PlainTextResponse:
    snapshot = await get_monitor_snapshot(dex_name)
    report = _build_simple_report(dex_name.lower(), snapshot)
    return PlainTextResponse(report)


@app.get("/monitor/{dex_name}/status")
async def get_monitor_status(dex_name: str) -> Dict[str, Any]:
    snapshot = await get_monitor_snapshot(dex_name)
    status = snapshot.get("account_status")
    if not status:
        status = _summarize_account_status(dex_name.lower(), snapshot)
    return status


@app.get("/apy/{dex_name}/simple", response_class=PlainTextResponse)
async def get_apy_simple(dex_name: str) -> PlainTextResponse:
    snapshot = await get_monitor_snapshot(dex_name)
    funding = snapshot.get("funding", {})

    if "error" in funding:
        return PlainTextResponse(
            f"{dex_name.upper()} APY ANALYSIS\nError: {funding['error']}\nTimestamp: {snapshot.get('timestamp', 'n/a')}\n"
        )

    rates = funding.get("effective_rates", {})
    projections = funding.get("projections", {})
    totals = funding.get("funding_totals", {})

    lines = [f"{dex_name.upper()} APY ANALYSIS"]
    lines.append(f"7d Effective Rate: {_format_percentage(rates.get('7_day_rate_percent', 0)/100 if rates else 0)}")
    lines.append(f"30d Effective Rate: {_format_percentage(rates.get('30_day_rate_percent', 0)/100 if rates else 0)}")
    lines.append(f"Monthly Projection: {_format_currency(projections.get('monthly_projected', 0))}")
    lines.append(f"Yearly Projection: {_format_currency(projections.get('yearly_projected', 0))}")
    lines.append(f"30d Funding Total: {_format_currency(totals.get('30_days', 0))}")
    lines.append(f"Timestamp: {snapshot.get('timestamp', 'n/a')}")
    return PlainTextResponse("\n".join(lines))


@app.get("/docs/examples")
async def api_examples() -> Dict[str, Any]:
    return {
        "start_bot": {
            "method": "POST",
            "url": "/start",
            "body": {
                "dex": "asterdex",
                "capital": "100",
                "spot_symbol": "ASTERUSDT",
                "futures_symbol": "ASTERUSDT",
                "batch_quote": "10",
                "mode": "buy_spot_short_futures",
            },
        },
        "check_status": {"method": "GET", "url": "/status/{job_id}"},
        "get_result": {"method": "GET", "url": "/result/{job_id}"},
        "monitor": {"method": "GET", "url": "/monitor/asterdex"},
        "monitor_simple": {"method": "GET", "url": "/monitor/asterdex/simple"},
        "apy_simple": {"method": "GET", "url": "/apy/asterdex/simple"},
    }


# -----------------------------------------------------------------------------
# Entry point guard for local debugging
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn  # type: ignore

    uvicorn.run("app.server:app", host="0.0.0.0", port=8000, reload=False)
