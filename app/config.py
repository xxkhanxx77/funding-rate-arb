#!/usr/bin/env python3
"""
Configuration management for AsterDex Funding Bot
Supports environment variables, JSON config files, and defaults
"""
import os
import json
import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    """Bot configuration with defaults"""
    # DEX selection
    dex: str = "asterdex"

    # Trading parameters
    capital: str = "100"
    spot_symbol: str = "ASTERUSDT"
    futures_symbol: str = "ASTERUSDT"
    batch_quote: str = "10"
    batch_delay: float = 1.0
    mode: str = "buy_spot_short_futures"
    recv_window: int = 5000

    # API credentials (from environment)
    api_key: str = ""
    api_secret: str = ""

    # Risk management
    max_leverage: int = 1
    stop_loss_percent: float = 0.0
    take_profit_percent: float = 0.0

    # Monitoring
    monitor_interval: int = 60
    enable_notifications: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=2)

class ConfigManager:
    """Manages bot configuration from multiple sources"""

    def __init__(self, config_file: Optional[str] = None):
        """
        Create a configuration manager.

        Args:
            config_file: Optional path to a JSON config file. When omitted, only
                environment variables (including those loaded from a `.env` file)
                will be considered.
        """

        self.config_file = config_file
        self.config = BotConfig()

    def load_config(self) -> BotConfig:
        """Load configuration from environment, file, and defaults (in that priority)"""

        # 1. Start with defaults
        config_dict = asdict(self.config)

        # 2. Load from config file if exists
        if self.config_file and os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    file_config = json.load(f)
                    config_dict.update(file_config)
                    logger.info(f"Loaded configuration from {self.config_file}")
            except Exception as e:
                logger.warning(f"Failed to load config file {self.config_file}: {e}")

        # 3. Override with environment variables (highest priority)
        env_mappings = {
            'FUNDING_DEX': 'dex',
            'FUNDING_CAPITAL': 'capital',
            'FUNDING_SPOT_SYMBOL': 'spot_symbol',
            'FUNDING_FUTURES_SYMBOL': 'futures_symbol',
            'FUNDING_BATCH_QUOTE': 'batch_quote',
            'FUNDING_BATCH_DELAY': 'batch_delay',
            'FUNDING_MODE': 'mode',
            'FUNDING_RECV_WINDOW': 'recv_window',
            'ASTERDEX_API_KEY': 'api_key',
            'ASTERDEX_API_SECRET': 'api_secret',
            'FUNDING_MAX_LEVERAGE': 'max_leverage',
            'FUNDING_STOP_LOSS': 'stop_loss_percent',
            'FUNDING_TAKE_PROFIT': 'take_profit_percent',
            'FUNDING_MONITOR_INTERVAL': 'monitor_interval',
            'FUNDING_ENABLE_NOTIFICATIONS': 'enable_notifications'
        }

        env_overrides = {}
        for env_var, config_key in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                # Convert to appropriate type
                if config_key in ['batch_delay', 'stop_loss_percent', 'take_profit_percent']:
                    env_overrides[config_key] = float(env_value)
                elif config_key in ['recv_window', 'max_leverage', 'monitor_interval']:
                    env_overrides[config_key] = int(env_value)
                elif config_key == 'enable_notifications':
                    env_overrides[config_key] = env_value.lower() in ('true', '1', 'yes', 'on')
                else:
                    env_overrides[config_key] = env_value

        if env_overrides:
            config_dict.update(env_overrides)
            logger.info(f"Applied {len(env_overrides)} environment variable overrides")

        # 4. Fallback API credentials if not set
        if not config_dict['api_key']:
            config_dict['api_key'] = os.getenv('ASTERDEX_API_KEY', '')
        if not config_dict['api_secret']:
            config_dict['api_secret'] = os.getenv('ASTERDEX_API_SECRET', '')

        # Create new config object
        self.config = BotConfig(**config_dict)
        return self.config

    def save_config(self, config: Optional[BotConfig] = None) -> bool:
        """Save current configuration to file"""
        if not self.config_file:
            logger.error("No config file path specified; cannot save configuration")
            return False

        try:
            config_to_save = config or self.config

            # Don't save sensitive data to file
            config_dict = config_to_save.to_dict()
            config_dict.pop('api_key', None)
            config_dict.pop('api_secret', None)

            with open(self.config_file, 'w') as f:
                json.dump(config_dict, f, indent=2)

            logger.info(f"Configuration saved to {self.config_file}")
            return True

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def create_example_config(self, filename: str = "bot_config.example.json") -> bool:
        """Create an example configuration file"""
        try:
            example_config = {
                "capital": "100",
                "spot_symbol": "ASTERUSDT",
                "futures_symbol": "ASTERUSDT",
                "batch_quote": "10",
                "batch_delay": 1.0,
                "mode": "buy_spot_short_futures",
                "recv_window": 5000,
                "max_leverage": 1,
                "stop_loss_percent": 0.0,
                "take_profit_percent": 0.0,
                "monitor_interval": 30,
                "enable_notifications": False
            }

            with open(filename, 'w') as f:
                json.dump(example_config, f, indent=2)

            logger.info(f"Example configuration created: {filename}")
            return True

        except Exception as e:
            logger.error(f"Failed to create example config: {e}")
            return False

    def get_bot_params(self) -> Dict[str, Any]:
        """Get parameters formatted for the trading bot"""
        config = self.load_config()

        return {
            'capital_usd': Decimal(config.capital),
            'spot_symbol': config.spot_symbol.upper(),
            'futures_symbol': config.futures_symbol.upper(),
            'batch_quote': Decimal(config.batch_quote),
            'batch_delay': config.batch_delay,
            'mode': config.mode,
            'recv_window': config.recv_window
        }

    def get_api_credentials(self) -> Dict[str, str]:
        """Get API credentials"""
        config = self.load_config()
        return {
            'api_key': config.api_key,
            'api_secret': config.api_secret
        }

    def print_config(self):
        """Print current configuration (hiding sensitive data)"""
        config = self.load_config()
        config_dict = config.to_dict()

        # Hide sensitive information
        if config_dict['api_key']:
            config_dict['api_key'] = config_dict['api_key'][:8] + "..."
        if config_dict['api_secret']:
            config_dict['api_secret'] = config_dict['api_secret'][:8] + "..."

        print("Current Configuration:")
        print(json.dumps(config_dict, indent=2))

def get_config() -> ConfigManager:
    """Get a configured ConfigManager instance"""
    return ConfigManager()

if __name__ == "__main__":
    # Test the configuration system
    config_mgr = ConfigManager()

    # Create example config
    config_mgr.create_example_config()

    # Print current config
    config_mgr.print_config()

    # Show bot parameters
    print("\nBot Parameters:")
    print(json.dumps({k: str(v) for k, v in config_mgr.get_bot_params().items()}, indent=2))
