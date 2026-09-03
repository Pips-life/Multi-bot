from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import DirectionSignal, Tick, PositionSizing, SYMBOL


@dataclass
class EntryEngine:
    """Detect the first measurable XAUUSD movement and emit its direction.

    A tick only creates a signal when its mid price changes from the previous
    tick. No candle or indicator is required. The host decides whether an
    emitted signal is currently allowed to open a position.
    """

    previous_mid: float | None = None

    def on_tick(self, tick: Tick) -> DirectionSignal | None:
        if tick.symbol.upper() != SYMBOL:
            return None
        current = tick.mid
        if self.previous_mid is None:
            self.previous_mid = current
            return None

        previous = self.previous_mid
        self.previous_mid = current
        if current > previous:
            return DirectionSignal("BUY", current, tick.time)
        if current < previous:
            return DirectionSignal("SELL", current, tick.time)
        return None


def size_from_balance(balance: float, broker_pip_value: float,
                      risk_fraction: float = 0.01) -> PositionSizing:
    """Convert account balance and broker pip value into order quantity.

    This deliberately keeps the sizing formula explicit. The live adapter
    should obtain the broker's symbol contract/pip value and enforce its
    volume min/max/step before submitting an order.
    """
    if balance <= 0:
        raise ValueError("balance must be positive")
    if broker_pip_value <= 0:
        raise ValueError("broker_pip_value must be positive")
    if not 0 < risk_fraction <= 1:
        raise ValueError("risk_fraction must be between 0 and 1")

    quantity = (balance * risk_fraction) / broker_pip_value
    return PositionSizing(balance, broker_pip_value, risk_fraction, quantity)
