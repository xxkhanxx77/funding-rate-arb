#!/usr/bin/env python3
"""Multi-DEX FastAPI server for funding-fee arbitrage bots."""

import logging
import os
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .config import ConfigManager
from dexes.factory import DexFactory

logger = logging.getLogger(__name__)

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
        with monitor_data_lock:
            monitor_data[dex_name] = snapshot
        _log_snapshot(dex_name, snapshot)
        resource["last_error"] = None
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

        print(f"\n=== {dex_name.upper()} Account Status on Startup ===")
        spot_balances = snapshot.get("summary", {}).get("spot", {}).get("balance", [])
        if spot_balances:
            print("Spot Holdings:")
            for asset in spot_balances:
                free = float(asset.get("free", 0))
                locked = float(asset.get("locked", 0))
                if free > 0 or locked > 0:
                    print(f"  {asset.get('asset', '?')}: {free:.6f}")

        futures_positions = snapshot.get("summary", {}).get("futures", {}).get("positions", [])
        if futures_positions:
            print("Futures Positions:")
            for pos in futures_positions:
                amt = pos.get("positionAmt") or pos.get("position_amt", 0)
                pnl = pos.get("unRealizedProfit") or pos.get("unrealized_pnl", 0)
                print(f"  {pos.get('symbol', '?')}: {amt} (PnL: ${pnl})")

        hedge = snapshot.get("hedging", {})
        ratio = float(hedge.get("average_efficiency", 0)) * 100
        status = "🟢 Active" if hedge.get("total_pairs", 0) > 0 and ratio >= 80 else "⭕ Inactive"
        health = "HEALTHY" if 95 <= ratio <= 105 else "NEEDS_ATTENTION"
        print(f"Strategy: {status}")
        print(f"Health: {health}")
        print(f"Hedge Ratio: {ratio:.2f}%")
        funding_data = snapshot.get("funding", {}) or {}
        funding_totals = funding_data.get("funding_totals") or {}
        if funding_totals:
            total_30d = float(funding_totals.get("30_days", 0))
            print(f"Funding Accumulated (30d): ${total_30d:.4f}")

        if funding_data and "error" not in funding_data:
            effective_rates = funding_data.get("effective_rates") or {}
            projections = funding_data.get("projections") or {}

            if effective_rates or projections:
                print("APY Analysis:")

                seven_rate = effective_rates.get("7_day_rate_percent")
                if seven_rate is not None:
                    print(
                        f"  7d Effective Rate: {_format_percentage(float(seven_rate) / 100)}"
                    )

                thirty_rate = effective_rates.get("30_day_rate_percent")
                if thirty_rate is not None:
                    print(
                        f"  30d Effective Rate: {_format_percentage(float(thirty_rate) / 100)}"
                    )
                    print(f"  Estimated APY: {float(thirty_rate):.2f}%")
                elif seven_rate is not None:
                    print(f"  Estimated APY: {float(seven_rate):.2f}%")

                monthly_projection = projections.get("monthly_projected")
                if monthly_projection is not None:
                    print(
                        f"  Monthly Projection: {_format_currency(monthly_projection)}"
                    )

                yearly_projection = projections.get("yearly_projected")
                if yearly_projection is not None:
                    print(
                        f"  Yearly Projection: {_format_currency(yearly_projection)}"
                    )

        mark_data = snapshot.get("mark_price", {}) or {}
        if mark_data:
            if "error" in mark_data:
                print(f"Mark Price: unavailable ({mark_data['error']})")
            else:
                print("Mark Price Overview:")

                mark_price_value = mark_data.get("mark_price")
                if mark_price_value is not None:
                    print(f"  Mark Price: {float(mark_price_value):.6f}")

                last_rate_percent = mark_data.get("last_funding_rate_percent")
                if last_rate_percent is not None:
                    print(f"  Last Funding Rate: {float(last_rate_percent):.4f}%")

                estimated_apy_percent = mark_data.get("estimated_apy_percent")
                if estimated_apy_percent is not None:
                    print(f"  Estimated Funding APY: {float(estimated_apy_percent):.2f}%")

                next_funding = mark_data.get("next_funding_time_iso")
                if next_funding:
                    print(f"  Next Funding: {next_funding}")

        print(f"=== {dex_name.upper()} Ready ===\n")

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
async def start_bot(request: BotStartRequest, background_tasks: BackgroundTasks) -> BotStartResponse:
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


@app.get("/monitor/{dex_name}/simple", response_class=PlainTextResponse)
async def get_monitor_simple(dex_name: str) -> PlainTextResponse:
    snapshot = await get_monitor_snapshot(dex_name)
    report = _build_simple_report(dex_name.lower(), snapshot)
    return PlainTextResponse(report)


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
