"""Standalone Velocity Expansion trading logic.

Cloned from the Velocity Expansion controller in Pips-life/Strat.1, but
intentionally separated from Strategy 002, its configuration, and the rest of
that application's execution stack.

Rules are supplied by the host app through ``trail_distance`` and the
execution adapter. This module contains only the position/paired-stop/reversal
logic; it does not define the new app's entry rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Protocol, Any


@dataclass
class Fill:
    order_id: str
    side: str
    quantity: float
    price: float
    timestamp: datetime


@dataclass
class OrderResult:
    status: str
    order_id: str = ""
    fill: Fill | None = None
    reason: str = ""


@dataclass
class OrderRequest:
    symbol: str
    side: str
    quantity: float
    order_type: str
    price: float
    client_order_id: str | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None


class ExecutionAdapter(Protocol):
    def submit(self, order: OrderRequest) -> OrderResult: ...
    def cancel_order(self, order_id: str) -> OrderResult: ...
    def on_bar(self, symbol: str, timestamp: datetime, high: float, low: float, close: float) -> list[Fill]: ...
    def close_position(self, symbol: str, timestamp: datetime, price: float | None = None) -> OrderResult: ...


@dataclass
class VelocityPair:
    position_order_id: str
    position_side: str
    quantity: float
    stop_order_id: str
    stop_price: float


class VelocityExpansionLogic:
    """Maintains one trailing opposite STOP for each live position.

    BUY position -> SELL STOP below the reference price.
    SELL position -> BUY STOP above the reference price.

    When the paired stop triggers, the source position is closed and the stop
    direction becomes the new market position. A fresh opposite stop is then
    installed. Trailing stops never move in a direction that increases risk.

    The host application decides *when/how to enter* and supplies the distance;
    no Strategy 002 entry/risk rules are embedded here.
    """

    def __init__(self, execution: ExecutionAdapter, trail_distance: float):
        if trail_distance <= 0:
            raise ValueError("trail_distance must be positive")
        self.execution = execution
        self.trail_distance = trail_distance
        self._pairs: Dict[str, VelocityPair] = {}

    @property
    def pairs(self) -> dict[str, VelocityPair]:
        return dict(self._pairs)

    def enter(self, symbol: str, side: str, quantity: float, price: float,
              timestamp: datetime | None = None) -> OrderResult:
        """Open a supplied position and immediately pair its opposite STOP."""
        if side not in {"BUY", "SELL"}:
            return OrderResult("REJECTED", reason="side must be BUY or SELL")
        if quantity <= 0:
            return OrderResult("REJECTED", reason="quantity must be positive")

        result = self.execution.submit(OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type="MARKET",
            price=price,
            timestamp=timestamp,
            metadata={"velocity_expansion": True},
        ))
        if result.status != "FILLED" or result.fill is None:
            return result

        self._install_stop(symbol, result.fill, timestamp or result.fill.timestamp)
        return result

    def on_bar(self, symbol: str, timestamp: datetime, high: float,
               low: float, close: float) -> list[Fill]:
        pair = self._pairs.get(symbol)
        if pair is not None:
            self._trail(symbol, pair, close, timestamp)

        fills = self.execution.on_bar(symbol, timestamp, high, low, close)
        for fill in fills:
            pair = self._pairs.get(symbol)
            if pair is None or fill.order_id != pair.stop_order_id:
                continue

            # Paired STOP is the reversal trigger.
            self.execution.close_position(symbol, timestamp, price=fill.price)
            self._pairs.pop(symbol, None)

            result = self.execution.submit(OrderRequest(
                symbol=symbol,
                side=fill.side,
                quantity=fill.quantity,
                order_type="MARKET",
                price=fill.price,
                timestamp=timestamp,
                metadata={"velocity_expansion_reversal": True},
            ))
            if result.status == "FILLED" and result.fill is not None:
                self._install_stop(symbol, result.fill, timestamp)

        return fills

    def close_all(self, timestamp: datetime, prices: dict[str, float]) -> None:
        for symbol, pair in list(self._pairs.items()):
            self.execution.cancel_order(pair.stop_order_id)
            if symbol in prices:
                self.execution.close_position(symbol, timestamp, prices[symbol])
            self._pairs.pop(symbol, None)

    def _install_stop(self, symbol: str, fill: Fill, timestamp: datetime) -> None:
        stop_side = "SELL" if fill.side == "BUY" else "BUY"
        stop_price = (
            fill.price - self.trail_distance
            if fill.side == "BUY"
            else fill.price + self.trail_distance
        )
        stop_id = f"VEL-STOP-{fill.order_id}"

        result = self.execution.submit(OrderRequest(
            symbol=symbol,
            side=stop_side,
            quantity=fill.quantity,
            order_type="STOP",
            price=stop_price,
            client_order_id=stop_id,
            timestamp=timestamp,
            metadata={
                "paired_position_order_id": fill.order_id,
                "oco_reversal": True,
            },
        ))
        if result.status != "NEW":
            raise RuntimeError(f"failed to install paired opposite stop: {result.reason}")

        self._pairs[symbol] = VelocityPair(
            fill.order_id, fill.side, fill.quantity, stop_id, stop_price
        )

    def _trail(self, symbol: str, pair: VelocityPair,
               reference_price: float, timestamp: datetime) -> None:
        candidate = (
            reference_price - self.trail_distance
            if pair.position_side == "BUY"
            else reference_price + self.trail_distance
        )

        # BUY stop only rises; SELL stop only falls.
        improves = (
            candidate > pair.stop_price
            if pair.position_side == "BUY"
            else candidate < pair.stop_price
        )
        if not improves:
            return

        cancelled = self.execution.cancel_order(pair.stop_order_id)
        if cancelled.status != "CANCELLED":
            return

        stop_side = "SELL" if pair.position_side == "BUY" else "BUY"
        result = self.execution.submit(OrderRequest(
            symbol=symbol,
            side=stop_side,
            quantity=pair.quantity,
            order_type="STOP",
            price=candidate,
            client_order_id=pair.stop_order_id,
            timestamp=timestamp,
            metadata={
                "paired_position_order_id": pair.position_order_id,
                "oco_reversal": True,
            },
        ))
        if result.status == "NEW":
            pair.stop_price = candidate
