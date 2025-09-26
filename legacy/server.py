#!/usr/bin/env python3
import json
import threading
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from legacy.funding_bot import AsterDexFundingBot, configure_logging
from monitor import AsterDexMonitor
from config import ConfigManager, get_config
from decimal import Decimal
import logging

# Configure logging
configure_logging("INFO")
logger = logging.getLogger(__name__)

# Global storage for bot instances and results
bot_instances: Dict[str, Dict[str, Any]] = {}
bot_results: Dict[str, Dict[str, Any]] = {}
bot_lock = threading.Lock()

# Global monitoring state
monitoring_active = True
latest_monitor_data = {}
monitor_lock = threading.Lock()

# Initialize configuration and monitor
config_manager = get_config()
monitor = AsterDexMonitor()

# Pydantic models
class BotStartRequest(BaseModel):
    capital: str = Field(default="100", description="Quote currency amount (USDT) to deploy")
    spot_symbol: str = Field(default="ASTERUSDT", description="Spot trading pair")
    futures_symbol: str = Field(default="ASTERUSDT", description="Futures contract")
    batch_quote: str = Field(default="10", description="Quote amount (USDT) per batch")
    batch_delay: float = Field(default=1.0, description="Delay in seconds between batches")
    mode: str = Field(default="buy_spot_short_futures", description="Trading direction")
    recv_window: int = Field(default=5000, description="API request timeout window")

class BotStartResponse(BaseModel):
    job_id: str
    status: str
    message: str

class BotStatus(BaseModel):
    job_id: str
    status: str
    config: Dict[str, str]
    created_time: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str

class JobListResponse(BaseModel):
    jobs: List[BotStatus]

class StopResponse(BaseModel):
    message: str
    recommendation: str

# FastAPI app
app = FastAPI(
    title="AsterDex Funding Bot API",
    description="REST API for managing AsterDex funding fee farming bot instances",
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    """Start background monitoring on server startup"""
    logger.info("Starting AsterDex Funding Bot API server...")

    # Initial monitoring check
    try:
        summary = monitor.get_account_summary()
        hedging = monitor.get_hedging_efficiency()
        pnl = monitor.get_position_pnl()

        logger.info(f"Initial monitoring check completed")
        print("\n=== Account Status on Startup ===")

        # Show spot balance
        spot_balance = summary.get("spot", {}).get("balance", [])
        if spot_balance:
            print("Spot Holdings:")
            for asset in spot_balance:
                if float(asset.get("free", 0)) > 0:
                    print(f"  {asset['asset']}: {asset['free']}")

        # Show futures positions
        futures_positions = summary.get("futures", {}).get("positions", [])
        if futures_positions:
            print("Futures Positions:")
            for pos in futures_positions:
                print(f"  {pos['symbol']}: {pos['positionAmt']} (PnL: ${pos['unRealizedProfit']})")

        # Show strategy status
        hedge_ratio = hedging.get("average_efficiency", 0) * 100
        is_active = hedging.get("total_pairs", 0) > 0 and hedging.get("average_efficiency", 0) > 0.8

        # Calculate gap for ASTER position
        gap_info = ""
        if hedging.get("hedged_pairs"):
            for pair in hedging.get("hedged_pairs", []):
                if pair.get("symbol") == "ASTERUSDT":
                    spot_qty = pair.get("spot_qty", 0)
                    futures_qty = pair.get("futures_qty", 0)
                    gap = abs(spot_qty - futures_qty)
                    gap_usd = gap * 2.0  # Approximate ASTER price
                    gap_info = f"Gap: {gap:.2f} ASTER (~${gap_usd:.2f})"

        strategy_status = "🟢 Active" if is_active else "⭕ Inactive"
        health = "HEALTHY" if hedge_ratio > 95 else "NEEDS_ATTENTION"

        print(f"Strategy: {strategy_status}")
        print(f"Health: {health}")
        print(f"Hedge Ratio: {hedge_ratio:.2f}%")
        if gap_info:
            print(f"{gap_info}")

        # Get funding payments history
        try:
            funding_payments = monitor.get_funding_payments("ASTERUSDT", days=30)
            total_funding = sum(float(payment.get("income", 0)) for payment in funding_payments)
            if total_funding != 0:
                print(f"Funding Accumulated (30d): ${total_funding:.4f}")
        except:
            print("Funding History: Loading...")

        print("=== Server Ready ===\n")

    except Exception as e:
        logger.warning(f"Initial monitoring check failed: {e}")

    # Start background monitoring thread
    import threading
    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()
    logger.info("Background monitoring started")

class BotRunner:
    def __init__(self, job_id: str, bot_config: Dict[str, Any]):
        self.job_id = job_id
        self.bot_config = bot_config
        self.status = "pending"
        self.error = None
        self.result = None
        self.start_time = None
        self.end_time = None

    def run(self):
        try:
            with bot_lock:
                bot_instances[self.job_id]["status"] = "running"
                bot_instances[self.job_id]["start_time"] = datetime.now().isoformat()

            self.start_time = datetime.now()
            logger.info(f"Starting bot job {self.job_id}")

            bot = AsterDexFundingBot(**self.bot_config)
            result = bot.execute()

            self.end_time = datetime.now()
            self.result = result
            self.status = "completed"

            with bot_lock:
                bot_instances[self.job_id]["status"] = "completed"
                bot_instances[self.job_id]["end_time"] = self.end_time.isoformat()
                bot_results[self.job_id] = result

            logger.info(f"Bot job {self.job_id} completed successfully")

        except Exception as e:
            self.end_time = datetime.now()
            self.status = "failed"
            self.error = str(e)

            with bot_lock:
                bot_instances[self.job_id]["status"] = "failed"
                bot_instances[self.job_id]["error"] = str(e)
                bot_instances[self.job_id]["end_time"] = self.end_time.isoformat()

            logger.error(f"Bot job {self.job_id} failed: {e}")

def run_bot_in_background(job_id: str, bot_config: Dict[str, Any]):
    """Background task to run the bot"""
    bot_runner = BotRunner(job_id, bot_config)
    bot_runner.run()

def background_monitor():
    """Background monitoring task that runs every 30 seconds"""
    while monitoring_active:
        try:
            # Get comprehensive monitoring data
            summary = monitor.get_account_summary()
            pnl = monitor.get_position_pnl()
            hedging = monitor.get_hedging_efficiency()

            # Store latest data
            with monitor_lock:
                latest_monitor_data.update({
                    "timestamp": datetime.now().isoformat(),
                    "summary": summary,
                    "pnl": pnl,
                    "hedging": hedging,
                    "is_active": hedging.get("total_pairs", 0) > 0 and hedging.get("average_efficiency", 0) > 0.8
                })

            logger.info(f"Monitor update: PnL=${pnl.get('total_unrealized_pnl', 0)}, "
                       f"Strategy: {'Active' if hedging.get('total_pairs', 0) > 0 else 'Inactive'}")

        except Exception as e:
            logger.error(f"Background monitoring error: {e}")

        # Wait 30 seconds before next update
        import time
        time.sleep(30)

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint with basic info"""
    return {
        "name": "AsterDex Funding Bot API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat()
    )

@app.post("/start", response_model=BotStartResponse)
async def start_bot(request: BotStartRequest = None, background_tasks: BackgroundTasks = None):
    """Start a new bot instance with given parameters or from config file"""
    try:
        if request:
            # Use provided parameters
            capital_usd = Decimal(request.capital)
            batch_quote = Decimal(request.batch_quote)

            # Validate mode
            valid_modes = ["buy_spot_short_futures", "sell_spot_long_futures"]
            if request.mode not in valid_modes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid mode. Must be one of: {valid_modes}"
                )

            # Create bot configuration
            bot_config = {
                "capital_usd": capital_usd,
                "spot_symbol": request.spot_symbol.upper(),
                "futures_symbol": request.futures_symbol.upper(),
                "batch_quote": batch_quote,
                "batch_delay": request.batch_delay,
                "mode": request.mode,
                "recv_window": request.recv_window
            }
        else:
            # Use configuration file
            bot_config = config_manager.get_bot_params()

        # Generate job ID
        job_id = str(uuid.uuid4())

        # Store job info
        with bot_lock:
            bot_instances[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "config": {k: str(v) for k, v in bot_config.items()},
                "created_time": datetime.now().isoformat(),
                "start_time": None,
                "end_time": None,
                "error": None
            }

        # Add background task
        background_tasks.add_task(run_bot_in_background, job_id, bot_config)

        return BotStartResponse(
            job_id=job_id,
            status="started",
            message="Bot started successfully"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameter value: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start bot: {str(e)}"
        )

@app.get("/status/{job_id}", response_model=BotStatus)
async def get_bot_status(job_id: str):
    """Get status of a specific bot instance"""
    with bot_lock:
        if job_id not in bot_instances:
            raise HTTPException(status_code=404, detail="Job ID not found")

        bot_info = bot_instances[job_id].copy()

    return BotStatus(**bot_info)

@app.get("/result/{job_id}")
async def get_bot_result(job_id: str):
    """Get the result of a completed bot instance"""
    with bot_lock:
        if job_id not in bot_instances:
            raise HTTPException(status_code=404, detail="Job ID not found")

        bot_info = bot_instances[job_id]
        if bot_info["status"] != "completed":
            raise HTTPException(
                status_code=400,
                detail=f"Bot job not completed. Current status: {bot_info['status']}"
            )

        if job_id not in bot_results:
            raise HTTPException(status_code=404, detail="Result not found")

        result = bot_results[job_id]

    return result

@app.get("/jobs", response_model=JobListResponse)
async def list_jobs():
    """List all bot jobs"""
    with bot_lock:
        jobs = [BotStatus(**job) for job in bot_instances.values()]

    return JobListResponse(jobs=jobs)

@app.post("/stop/{job_id}", response_model=StopResponse)
async def stop_bot(job_id: str):
    """Stop a running bot instance (note: this will not actually stop the trading bot once started)"""
    with bot_lock:
        if job_id not in bot_instances:
            raise HTTPException(status_code=404, detail="Job ID not found")

        bot_info = bot_instances[job_id]
        if bot_info["status"] not in ["pending", "running"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot stop job. Current status: {bot_info['status']}"
            )

    # Note: The actual trading bot cannot be stopped mid-execution safely
    return StopResponse(
        message="Stop requested, but trading bot cannot be safely stopped mid-execution",
        recommendation="Wait for current batch to complete"
    )

@app.get("/docs/examples")
async def api_examples():
    """Get API usage examples"""
    return {
        "start_bot": {
            "method": "POST",
            "url": "/start",
            "body": {
                "capital": "1000",
                "spot_symbol": "ASTERUSDT",
                "futures_symbol": "ASTERUSDT",
                "batch_quote": "100",
                "batch_delay": 2.0,
                "mode": "buy_spot_short_futures"
            }
        },
        "check_status": {
            "method": "GET",
            "url": "/status/{job_id}"
        },
        "get_result": {
            "method": "GET",
            "url": "/result/{job_id}"
        },
        "list_jobs": {
            "method": "GET",
            "url": "/jobs"
        }
    }

# Dashboard and Monitoring Endpoints
@app.get("/dashboard")
async def dashboard():
    """Get complete dashboard data in JSON format"""
    try:
        summary = monitor.get_account_summary()
        risk = monitor.get_risk_metrics()
        pnl = monitor.get_position_pnl()
        hedging = monitor.get_hedging_efficiency()
        payments = monitor.get_funding_payments(days=7)

        return {
            "summary": summary,
            "risk": risk,
            "pnl": pnl,
            "hedging": hedging,
            "funding_payments": payments,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dashboard error: {str(e)}")

@app.get("/api/monitor/summary")
async def get_monitor_summary():
    """Get comprehensive account summary"""
    return monitor.get_account_summary()

@app.get("/api/monitor/risk")
async def get_risk_metrics():
    """Get risk metrics"""
    return monitor.get_risk_metrics()

@app.get("/api/monitor/pnl")
async def get_position_pnl():
    """Get position PnL data"""
    return monitor.get_position_pnl()

@app.get("/api/monitor/hedging")
async def get_hedging_efficiency():
    """Get hedging efficiency metrics"""
    return monitor.get_hedging_efficiency()

@app.get("/api/monitor/funding-payments")
async def get_funding_payments(symbol: Optional[str] = None, days: int = 7):
    """Get funding payment history"""
    return monitor.get_funding_payments(symbol, days)

@app.get("/api/monitor/positions")
async def get_positions():
    """Get current futures positions"""
    return monitor.get_futures_positions()

@app.get("/api/monitor/balance/spot")
async def get_spot_balance():
    """Get spot account balance"""
    return monitor.get_spot_balance()

@app.get("/api/monitor/balance/futures")
async def get_futures_balance():
    """Get futures account balance"""
    return monitor.get_futures_balance()

@app.get("/api/monitor/latest")
async def get_latest_monitor_data():
    """Get latest cached monitoring data (updated every 30s)"""
    with monitor_lock:
        if not latest_monitor_data:
            return {"error": "No monitoring data available yet"}
        return latest_monitor_data.copy()

@app.get("/api/monitor/live-status")
async def get_live_status():
    """Get live status summary in text format"""
    try:
        with monitor_lock:
            data = latest_monitor_data.copy()

        if not data:
            return {"status": "⏳ Monitoring starting up..."}

        pnl = data.get("pnl", {})
        hedging = data.get("hedging", {})

        status_text = f"""🔴 AsterDex Funding Bot Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy: {'🟢 Active' if data.get('is_active', False) else '⭕ Inactive'}
PnL: ${pnl.get('total_unrealized_pnl', 0)}
Hedge Ratio: {hedging.get('average_efficiency', 0):.1%}
Pairs: {hedging.get('total_pairs', 0)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Updated: {data.get('timestamp', 'Unknown')}"""

        return {"status": status_text}

    except Exception as e:
        return {"error": f"Status error: {str(e)}"}

# Configuration Management Endpoints
@app.get("/config")
async def get_config():
    """Get current configuration"""
    config = config_manager.load_config()
    config_dict = config.to_dict()

    # Hide sensitive information
    if config_dict.get('api_key'):
        config_dict['api_key'] = config_dict['api_key'][:8] + "..."
    if config_dict.get('api_secret'):
        config_dict['api_secret'] = config_dict['api_secret'][:8] + "..."

    return {
        "config": config_dict,
        "source": "Environment variables override config file",
        "config_file": config_manager.config_file
    }

@app.post("/config")
async def update_config(new_config: dict):
    """Update configuration and save to file"""
    try:
        # Validate the new config
        from config import BotConfig

        # Get current config
        current = config_manager.load_config().to_dict()

        # Update with new values (but preserve API credentials)
        updated = current.copy()
        for key, value in new_config.items():
            if key not in ['api_key', 'api_secret']:  # Don't allow updating credentials via API
                updated[key] = value

        # Create new config object to validate
        new_config_obj = BotConfig(**updated)

        # Save to file
        if config_manager.save_config(new_config_obj):
            return {
                "status": "success",
                "message": "Configuration updated successfully",
                "config": new_config_obj.to_dict()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to save configuration")

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {str(e)}")

@app.post("/start-from-config")
async def start_bot_from_config(background_tasks: BackgroundTasks):
    """Start bot using current configuration file"""
    try:
        # Get bot parameters from config
        bot_config = config_manager.get_bot_params()

        # Generate job ID
        job_id = str(uuid.uuid4())

        # Store job info
        with bot_lock:
            bot_instances[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "config": {k: str(v) for k, v in bot_config.items()},
                "created_time": datetime.now().isoformat(),
                "start_time": None,
                "end_time": None,
                "error": None
            }

        # Add background task
        background_tasks.add_task(run_bot_in_background, job_id, bot_config)

        return BotStartResponse(
            job_id=job_id,
            status="started",
            message="Bot started from configuration file"
        )

    except Exception as e:
        logger.error(f"Error starting bot from config: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start bot from config: {str(e)}"
        )

@app.get("/config/example")
async def get_example_config():
    """Get example configuration"""
    return {
        "capital": "100",
        "spot_symbol": "ASTERUSDT",
        "futures_symbol": "ASTERUSDT",
        "batch_quote": "10",
        "batch_delay": 1,
        "mode": "buy_spot_short_futures",
        "recv_window": 5000,
        "max_leverage": 1,
        "stop_loss_percent": 0.0,
        "take_profit_percent": 0.0,
        "monitor_interval": 30,
        "enable_notifications": False
    }

@app.get("/api/funding-bot/status")
async def get_funding_bot_status():
    """Get comprehensive funding bot position status"""
    try:
        # Get futures positions and balance (most reliable)
        futures_positions = monitor.get_futures_positions()
        futures_balance = monitor.get_futures_balance()

        # Try to get spot balance with fallback
        try:
            spot_data = monitor.get_spot_balance()
        except:
            # Use the direct method we know works
            from legacy.funding_bot import AsterDexFundingBot
            from decimal import Decimal
            bot = AsterDexFundingBot(capital_usd=Decimal("10"), batch_quote=Decimal("10"))
            account_data = bot._request(bot.spot_base_url, "/api/v1/account", signed=True)
            spot_data = account_data.get("balances", [])

        # Parse positions
        active_positions = []
        total_pnl = 0

        for pos in futures_positions:
            size = float(pos.get("positionAmt", 0))
            if abs(size) > 0.001:
                pnl = float(pos.get("unRealizedProfit", 0))
                total_pnl += pnl
                active_positions.append({
                    "symbol": pos.get("symbol"),
                    "side": "LONG" if size > 0 else "SHORT",
                    "size": abs(size),
                    "entry_price": float(pos.get("entryPrice", 0)),
                    "mark_price": float(pos.get("markPrice", 0)),
                    "pnl": pnl,
                    "notional": abs(size) * float(pos.get("markPrice", 0))
                })

        # Parse spot holdings
        spot_holdings = {}
        for asset in spot_data:
            symbol = asset.get("asset", "")
            free = float(asset.get("free", 0))
            locked = float(asset.get("locked", 0))
            if free > 0 or locked > 0:
                spot_holdings[symbol] = {
                    "free": free,
                    "locked": locked,
                    "total": free + locked
                }

        # Calculate funding bot specific metrics
        aster_spot = spot_holdings.get("ASTER", {}).get("total", 0)
        aster_futures = next((p for p in active_positions if p["symbol"] == "ASTERUSDT"), None)

        funding_bot_status = {
            "is_active": aster_spot > 0 and aster_futures is not None,
            "strategy_health": "UNKNOWN",
            "hedge_ratio": 0
        }

        if aster_spot > 0 and aster_futures:
            hedge_ratio = aster_futures["size"] / aster_spot
            funding_bot_status.update({
                "hedge_ratio": hedge_ratio,
                "is_properly_hedged": 0.95 <= hedge_ratio <= 1.05,
                "strategy_health": "HEALTHY" if (
                    aster_futures["side"] == "SHORT" and 0.95 <= hedge_ratio <= 1.05
                ) else "NEEDS_ATTENTION"
            })

        # Get current funding rate
        try:
            funding_info = monitor.get_funding_info(["ASTERUSDT"])
            current_rate = 0
            if funding_info:
                rate_str = funding_info[0].get("premium_index", {}).get("lastFundingRate", "0")
                current_rate = float(rate_str) * 100
        except:
            current_rate = 0

        return {
            "timestamp": datetime.now().isoformat(),
            "funding_bot": funding_bot_status,
            "spot_holdings": spot_holdings,
            "futures_positions": active_positions,
            "portfolio_summary": {
                "total_pnl": total_pnl,
                "active_positions": len(active_positions),
                "futures_balance": float(futures_balance.get("totalWalletBalance", 0)),
                "available_balance": float(futures_balance.get("availableBalance", 0))
            },
            "funding_rate": {
                "current_rate_percent": current_rate,
                "estimated_daily_income": aster_spot * 2.0 * (current_rate / 100) * 3 if aster_spot > 0 else 0
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting funding bot status: {str(e)}")

@app.get("/api/funding-bot/simple")
async def get_simple_funding_status():
    """Get simple funding bot status (text format)"""
    try:
        data = await get_funding_bot_status()

        # Format as simple text response
        status = data["funding_bot"]
        portfolio = data["portfolio_summary"]
        funding = data["funding_rate"]

        # Get funding payment history for real PnL
        try:
            funding_payments = monitor.get_funding_payments("ASTERUSDT", days=30)
            total_funding_30d = sum(float(payment.get("income", 0)) for payment in funding_payments)
            funding_payments_7d = monitor.get_funding_payments("ASTERUSDT", days=7)
            total_funding_7d = sum(float(payment.get("income", 0)) for payment in funding_payments_7d)
        except:
            total_funding_30d = 0
            total_funding_7d = 0

        response = f"""FUNDING BOT STATUS:
Strategy: {'🟢 Active' if status['is_active'] else '⭕ Inactive'}
Health: {status['strategy_health']}
Hedge Ratio: {status['hedge_ratio']:.2%}

PORTFOLIO:
Total PnL: ${portfolio['total_pnl']:.2f}
Positions: {portfolio['active_positions']}
Available: ${portfolio['available_balance']:.2f}

FUNDING:
Current Rate: {funding['current_rate_percent']:.4f}%
Est. Daily: ${funding['estimated_daily_income']:.4f}
Accumulated (7d): ${total_funding_7d:.4f}
Accumulated (30d): ${total_funding_30d:.4f}

Updated: {data['timestamp']}
"""
        return {"status": response}

    except Exception as e:
        return {"error": str(e)}

@app.get("/api/funding/analytics")
async def get_funding_analytics():
    """Get comprehensive funding fee analytics and historical data"""
    try:
        # Get funding payments for different periods
        payments_1d = monitor.get_funding_payments("ASTERUSDT", days=1)
        payments_7d = monitor.get_funding_payments("ASTERUSDT", days=7)
        payments_30d = monitor.get_funding_payments("ASTERUSDT", days=30)
        payments_90d = monitor.get_funding_payments("ASTERUSDT", days=90)

        # Calculate totals
        total_1d = sum(float(p.get("income", 0)) for p in payments_1d)
        total_7d = sum(float(p.get("income", 0)) for p in payments_7d)
        total_30d = sum(float(p.get("income", 0)) for p in payments_30d)
        total_90d = sum(float(p.get("income", 0)) for p in payments_90d)

        # Calculate averages
        avg_daily_7d = total_7d / 7 if total_7d != 0 else 0
        avg_daily_30d = total_30d / 30 if total_30d != 0 else 0

        # Get current position size for rate calculations
        positions = monitor.get_futures_positions()
        aster_position = next((p for p in positions if p.get("symbol") == "ASTERUSDT"), None)
        position_size = abs(float(aster_position.get("positionAmt", 0))) if aster_position else 0

        # Calculate effective funding rates
        effective_rate_7d = (total_7d / (position_size * 2.0 * 7 * 3)) * 100 if position_size > 0 and total_7d != 0 else 0
        effective_rate_30d = (total_30d / (position_size * 2.0 * 30 * 3)) * 100 if position_size > 0 and total_30d != 0 else 0

        return {
            "timestamp": datetime.now().isoformat(),
            "position_size_aster": position_size,
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
        raise HTTPException(status_code=500, detail=f"Funding analytics error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
