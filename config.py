"""Backwards-compatible config module shim."""

from app.config import *  # noqa: F401,F403
from app.config import BotConfig, ConfigManager, get_config

__all__ = [name for name in globals() if not name.startswith('_')]
