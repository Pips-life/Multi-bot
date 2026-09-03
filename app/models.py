from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SYMBOL = "XAUUSD"


@dataclass(frozen=True)
class AccountConfig:
    """Non-secret account connection settings supplied by the user."""

    account_id: str
    metaapi_token: str
    broker_pip_value: float


@dataclass(frozen=True)
class Tick:
    symbol: str
    bid: float
    ask: float
    time: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class DirectionSignal:
    side: str
    price: float
    time: datetime


@dataclass(frozen=True)
class PositionSizing:
    balance: float
    pip_value: float
    risk_fraction: float
    quantity: float
