#!/usr/bin/env python3
"""
Base interface for DEX integrations
Defines common methods that all DEX implementations must provide
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime


class BaseDexInterface(ABC):
    """Abstract base class for DEX integrations"""

    def __init__(self, api_key: str, api_secret: str, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret

    @abstractmethod
    def get_name(self) -> str:
        """Get the name of the DEX"""
        pass

    @abstractmethod
    def get_spot_balance(self) -> List[Dict[str, Any]]:
        """Get spot account balance"""
        pass

    @abstractmethod
    def get_futures_balance(self) -> Dict[str, Any]:
        """Get futures account balance"""
        pass

    @abstractmethod
    def get_futures_positions(self) -> List[Dict[str, Any]]:
        """Get current futures positions"""
        pass

    @abstractmethod
    def get_funding_payments(self, symbol: str = None, days: int = 7) -> List[Dict[str, Any]]:
        """Get funding payment history"""
        pass

    @abstractmethod
    def get_spot_price(self, symbol: str) -> Decimal:
        """Get current spot price for a symbol"""
        pass

    @abstractmethod
    def get_futures_price(self, symbol: str) -> Decimal:
        """Get current futures price for a symbol"""
        pass

    @abstractmethod
    def place_spot_market_buy(self, symbol: str, quote_amount: Decimal) -> Dict[str, Any]:
        """Place a spot market buy order"""
        pass

    @abstractmethod
    def place_spot_market_sell(self, symbol: str, base_amount: Decimal) -> Dict[str, Any]:
        """Place a spot market sell order"""
        pass

    @abstractmethod
    def place_futures_market_long(self, symbol: str, quantity: Decimal) -> Dict[str, Any]:
        """Place a futures market long order"""
        pass

    @abstractmethod
    def place_futures_market_short(self, symbol: str, quantity: Decimal) -> Dict[str, Any]:
        """Place a futures market short order"""
        pass

    @abstractmethod
    def get_symbol_info(self, symbol: str, market_type: str = "spot") -> Dict[str, Any]:
        """Get symbol trading information (lot sizes, min quantities, etc.)"""
        pass

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Set leverage for a futures symbol"""
        pass


class BaseFundingBot(ABC):
    """Abstract base class for funding fee farming bots"""

    def __init__(self, dex: BaseDexInterface, capital_usd: Decimal, **kwargs):
        self.dex = dex
        self.capital_usd = capital_usd

    @abstractmethod
    def execute_strategy(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """Execute the funding fee farming strategy"""
        pass

    @abstractmethod
    def get_strategy_status(self) -> Dict[str, Any]:
        """Get current strategy status"""
        pass


class BaseMonitor(ABC):
    """Abstract base class for portfolio monitoring"""

    def __init__(self, dex: BaseDexInterface):
        self.dex = dex

    @abstractmethod
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get comprehensive portfolio summary"""
        pass

    @abstractmethod
    def get_hedging_efficiency(self) -> Dict[str, Any]:
        """Calculate hedging efficiency between spot and futures"""
        pass

    @abstractmethod
    def get_risk_metrics(self) -> Dict[str, Any]:
        """Calculate risk metrics for the portfolio"""
        pass

    @abstractmethod
    def get_funding_analytics(self, symbol: str = None, days: int = 30) -> Dict[str, Any]:
        """Get funding fee analytics and projections"""
        pass
