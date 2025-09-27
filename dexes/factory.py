#!/usr/bin/env python3
"""
DEX Factory for creating DEX instances
Supports multiple DEX implementations
"""

import os
import logging
import inspect
from typing import Dict, Any, Optional, Tuple, List
from decimal import Decimal

from .base.dex_interface import BaseDexInterface, BaseFundingBot, BaseMonitor
from .asterdex.client import AsterDexClient
from .asterdex.funding_bot import AsterDexFundingBot
from .asterdex.monitor import AsterDexMonitor

logger = logging.getLogger(__name__)


class DexFactory:
    """Factory for creating DEX instances"""

    SUPPORTED_DEXES = {
        "asterdex": {
            "client": AsterDexClient,
            "bot": AsterDexFundingBot,
            "monitor": AsterDexMonitor,
            "env_prefix": "ASTERDEX"
        }
        # Future DEXes will be added here
        # "hyperliquid": {
        #     "client": HyperliquidClient,
        #     "bot": HyperliquidFundingBot,
        #     "monitor": HyperliquidMonitor,
        #     "env_prefix": "HYPERLIQUID"
        # }
    }

    @classmethod
    def create_client(cls, dex_name: str, **kwargs) -> BaseDexInterface:
        """Create a DEX client instance"""
        dex_name = dex_name.lower()

        if dex_name not in cls.SUPPORTED_DEXES:
            raise ValueError(f"Unsupported DEX: {dex_name}. Supported: {list(cls.SUPPORTED_DEXES.keys())}")

        dex_config = cls.SUPPORTED_DEXES[dex_name]
        client_class = dex_config["client"]
        env_prefix = dex_config["env_prefix"]

        # Get API credentials from environment or kwargs
        api_key = kwargs.get("api_key") or os.getenv(f"{env_prefix}_API_KEY")
        api_secret = kwargs.get("api_secret") or os.getenv(f"{env_prefix}_API_SECRET")

        if not api_key or not api_secret:
            raise RuntimeError(f"Missing API credentials for {dex_name}. Set {env_prefix}_API_KEY and {env_prefix}_API_SECRET")

        # Create client instance; ignore kwargs the client does not accept
        raw_client_kwargs = {
            "api_key": api_key,
            "api_secret": api_secret,
            **{k: v for k, v in kwargs.items() if k not in ["api_key", "api_secret"]}
        }

        signature = inspect.signature(client_class.__init__)
        accepts_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )

        if accepts_var_kwargs:
            client_kwargs = raw_client_kwargs
        else:
            accepted_params = {
                name
                for name, param in signature.parameters.items()
                if name != "self" and param.kind != inspect.Parameter.VAR_POSITIONAL
            }
            client_kwargs = {
                key: value
                for key, value in raw_client_kwargs.items()
                if key in accepted_params
            }

            ignored_keys = set(raw_client_kwargs) - set(client_kwargs)
            if ignored_keys:
                logger.debug(
                    "Ignoring unsupported client kwargs for %s: %s",
                    client_class.__name__,
                    sorted(ignored_keys),
                )

        logger.info(f"Creating {dex_name} client")
        return client_class(**client_kwargs)

    @classmethod
    def create_funding_bot(cls, dex_name: str, capital_usd: Decimal, **kwargs) -> BaseFundingBot:
        """Create a funding bot instance"""
        dex_name = dex_name.lower()

        if dex_name not in cls.SUPPORTED_DEXES:
            raise ValueError(f"Unsupported DEX: {dex_name}")

        dex_config = cls.SUPPORTED_DEXES[dex_name]
        bot_class = dex_config["bot"]

        # Create DEX client
        client = cls.create_client(dex_name, **kwargs)

        # Create bot instance
        bot_kwargs = {
            "dex": client,
            "capital_usd": capital_usd,
            **{k: v for k, v in kwargs.items() if k not in ["api_key", "api_secret"]}
        }

        logger.info(f"Creating {dex_name} funding bot with capital ${capital_usd}")
        return bot_class(**bot_kwargs)

    @classmethod
    def create_monitor(cls, dex_name: str, **kwargs) -> BaseMonitor:
        """Create a monitor instance"""
        dex_name = dex_name.lower()

        if dex_name not in cls.SUPPORTED_DEXES:
            raise ValueError(f"Unsupported DEX: {dex_name}")

        dex_config = cls.SUPPORTED_DEXES[dex_name]
        monitor_class = dex_config["monitor"]

        # Create DEX client
        client = cls.create_client(dex_name, **kwargs)

        logger.info(f"Creating {dex_name} monitor")
        return monitor_class(client)

    @classmethod
    def create_full_setup(cls, dex_name: str, capital_usd: Decimal, **kwargs) -> Tuple[BaseDexInterface, BaseFundingBot, BaseMonitor]:
        """Create client, bot, and monitor instances"""
        client = cls.create_client(dex_name, **kwargs)

        # Create bot with existing client
        dex_config = cls.SUPPORTED_DEXES[dex_name.lower()]
        bot_class = dex_config["bot"]
        monitor_class = dex_config["monitor"]

        bot_kwargs = {
            "dex": client,
            "capital_usd": capital_usd,
            **{k: v for k, v in kwargs.items() if k not in ["api_key", "api_secret"]}
        }

        bot = bot_class(**bot_kwargs)
        monitor = monitor_class(client)

        logger.info(f"Created full {dex_name} setup: client, bot (${capital_usd}), and monitor")
        return client, bot, monitor

    @classmethod
    def list_supported_dexes(cls) -> List[str]:
        """Get list of supported DEXes"""
        return list(cls.SUPPORTED_DEXES.keys())

    @classmethod
    def get_dex_info(cls, dex_name: str) -> Dict[str, Any]:
        """Get information about a specific DEX"""
        dex_name = dex_name.lower()

        if dex_name not in cls.SUPPORTED_DEXES:
            raise ValueError(f"Unsupported DEX: {dex_name}")

        config = cls.SUPPORTED_DEXES[dex_name]
        return {
            "name": dex_name,
            "env_prefix": config["env_prefix"],
            "required_env_vars": [
                f"{config['env_prefix']}_API_KEY",
                f"{config['env_prefix']}_API_SECRET"
            ],
            "client_class": config["client"].__name__,
            "bot_class": config["bot"].__name__,
            "monitor_class": config["monitor"].__name__
        }
