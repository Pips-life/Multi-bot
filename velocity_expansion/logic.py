"""Standalone Velocity Expansion position-management logic.

The management loop is cloned from Strat.1 but is independent from Strategy 002.
XAUUSD positions use the live executable opposite quote as the protective STOP:
BUY -> SELL STOP at bid; SELL -> BUY STOP at ask.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Protocol

SYMBOL = "XAUUSD"
REACTION_TARGET_MS = 0.10

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
    def close_position(self, symbol: str, timestamp: datetime, price: float | None = None) -> OrderResult: ...

@dataclass
class VelocityPair:
    position_order_id: str
    position_side: str
    quantity: float
    stop_order_id: str
    stop_price: float
    entry_price: float

class VelocityExpansionLogic:
    """One-position XAUUSD reversal loop using a live bid/ask STOP.

    BUY -> SELL STOP is placed at the current BID.
    SELL -> BUY STOP is placed at the current ASK.
    The STOP is never moved backwards, and is improved to each new favorable
    executable quote. When the broker confirms the STOP fill, that fill is the
    source-position exit/pocket event and immediately triggers one MARKET
    reversal in the stop direction.

    The local reaction target is 0.10ms. Broker/network execution latency is
    external and cannot be guaranteed by application code.
    """
    def __init__(self, execution: ExecutionAdapter, pip_size: float):
        if pip_size <= 0:
            raise ValueError("pip_size must be positive")
        self.execution = execution
        # Retained for API compatibility with existing callers. The STOP no
        # longer uses a pip-distance calculation.
        self.pip_size = pip_size
        self._pairs: Dict[str, VelocityPair] = {}
        self._handled_stop_fills: set[str] = set()
        self._last_bid: float | None = None
        self._last_ask: float | None = None

    @property
    def pairs(self) -> dict[str, VelocityPair]:
        return dict(self._pairs)

    def enter(self, side: str, quantity: float, price: float, timestamp: datetime | None = None) -> OrderResult:
        if side not in {"BUY", "SELL"}:
            return OrderResult("REJECTED", reason="side must be BUY or SELL")
        if quantity <= 0:
            return OrderResult("REJECTED", reason="quantity must be positive")
        result = self.execution.submit(OrderRequest(
            symbol=SYMBOL, side=side, quantity=quantity, order_type="MARKET", price=price,
            timestamp=timestamp, metadata={"velocity_expansion": True, "live_bid_ask_stop": True},
        ))
        if result.status == "FILLED" and result.fill is not None:
            self._install_stop(result.fill, timestamp or result.fill.timestamp)
        return result

    def on_tick(self, bid: float, ask: float, timestamp: datetime, fills: list[Fill] | None = None) -> list[Fill]:
        """Track executable quotes, improve the live STOP, then process fills."""
        if bid <= 0 or ask <= 0 or bid > ask:
            return fills or []
        self._last_bid = bid
        self._last_ask = ask

        pair = self._pairs.get(SYMBOL)
        if pair is not None:
            self._trail(pair, bid, ask, timestamp)
        for fill in fills or []:
            pair = self._pairs.get(SYMBOL)
            if pair is not None and fill.order_id == pair.stop_order_id:
                self._handle_stop_fill(fill, timestamp)
        return fills or []

    def close_all(self, timestamp: datetime, price: float | None = None) -> None:
        for symbol, pair in list(self._pairs.items()):
            self.execution.cancel_order(pair.stop_order_id)
            self.execution.close_position(symbol, timestamp, price)
            self._pairs.pop(symbol, None)

    def _current_stop_price(self, side: str, fallback: float) -> float:
        if side == "BUY":
            return self._last_bid if self._last_bid is not None else fallback
        return self._last_ask if self._last_ask is not None else fallback

    def _install_stop(self, fill: Fill, timestamp: datetime) -> None:
        stop_side = "SELL" if fill.side == "BUY" else "BUY"
        stop_price = self._current_stop_price(fill.side, fill.price)
        stop_id = f"VEL-LIVE-STOP-{fill.order_id}"
        result = self.execution.submit(OrderRequest(
            symbol=SYMBOL, side=stop_side, quantity=fill.quantity, order_type="STOP",
            price=stop_price, client_order_id=stop_id, timestamp=timestamp,
            metadata={
                "paired_position_order_id": fill.order_id,
                "oco_reversal": True,
                "stop_at_live_executable_quote": True,
                "stop_reference": "BID" if fill.side == "BUY" else "ASK",
                "reaction_target_ms": REACTION_TARGET_MS,
            },
        ))
        if result.status != "NEW":
            raise RuntimeError(f"failed to install live bid/ask paired STOP: {result.reason}")
        self._pairs[SYMBOL] = VelocityPair(fill.order_id, fill.side, fill.quantity, stop_id, stop_price, fill.price)

    def _trail(self, pair: VelocityPair, bid: float, ask: float, timestamp: datetime) -> None:
        # The STOP sits directly on the executable quote on the opposite side:
        # BUY protection/reversal at BID; SELL protection/reversal at ASK.
        candidate = bid if pair.position_side == "BUY" else ask
        improves = candidate > pair.stop_price if pair.position_side == "BUY" else candidate < pair.stop_price
        if not improves:
            return

        cancelled = self.execution.cancel_order(pair.stop_order_id)
        if cancelled.status != "CANCELLED":
            return
        stop_side = "SELL" if pair.position_side == "BUY" else "BUY"
        result = self.execution.submit(OrderRequest(
            symbol=SYMBOL, side=stop_side, quantity=pair.quantity, order_type="STOP",
            price=candidate, client_order_id=pair.stop_order_id, timestamp=timestamp,
            metadata={
                "paired_position_order_id": pair.position_order_id,
                "oco_reversal": True,
                "stop_at_live_executable_quote": True,
                "stop_reference": "BID" if pair.position_side == "BUY" else "ASK",
                "reaction_target_ms": REACTION_TARGET_MS,
            },
        ))
        if result.status == "NEW":
            pair.stop_price = candidate

    def _handle_stop_fill(self, fill: Fill, timestamp: datetime) -> None:
        pair = self._pairs.get(SYMBOL)
        if pair is None or fill.order_id != pair.stop_order_id:
            return
        if fill.order_id in self._handled_stop_fills:
            return
        self._handled_stop_fills.add(fill.order_id)

        # Broker-confirmed STOP fill has already closed the source position and
        # realized its result. Do not call close_position here: on a netting
        # account that can race the reversal and flatten the new position.
        self._pairs.pop(SYMBOL, None)

        reaction_ts = timestamp
        result = self.execution.submit(OrderRequest(
            symbol=SYMBOL, side=fill.side, quantity=fill.quantity, order_type="MARKET", price=fill.price,
            timestamp=reaction_ts,
            client_order_id=f"VEL-LIVE-REV-{fill.order_id}",
            metadata={
                "velocity_expansion_reversal": True,
                "trigger_stop_order_id": fill.order_id,
                "trigger_fill_price": fill.price,
                "trigger_fill_timestamp": fill.timestamp.isoformat(),
                "reaction_timestamp": reaction_ts.isoformat(),
                "reaction_target_ms": REACTION_TARGET_MS,
                "pocket_profit_before_reverse": True,
                "broker_confirmed_exit": True,
                "stop_at_live_executable_quote": True,
            },
        ))
        if result.status == "FILLED" and result.fill is not None:
            self._install_stop(result.fill, reaction_ts)
