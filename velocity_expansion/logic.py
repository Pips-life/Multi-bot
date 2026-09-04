"""Standalone Velocity Expansion position-management logic.

The management loop is cloned from Strat.1 but is independent from Strategy 002.
XAUUSD positions use the live executable opposite quote as the protective STOP:
BUY -> SELL STOP at bid; SELL -> BUY STOP at ask.
Each position also gets its own fixed 130-pip TAKE PROFIT.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Protocol

SYMBOL = "XAUUSD"
REACTION_TARGET_MS = 0.10
TAKE_PROFIT_PIPS = 130

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
    take_profit_order_id: str
    take_profit_price: float

class VelocityExpansionLogic:
    """Multi-position XAUUSD manager with independent live trailing SL + fixed TP.

    Every filled position is managed independently:
    - BUY -> SELL STOP at the current BID and fixed TP 130 pips above entry.
    - SELL -> BUY STOP at the current ASK and fixed TP 130 pips below entry.
    - The STOP only moves in the profitable direction, directly tracking the
      executable bid/ask. It never moves backwards.
    - A STOP fill is treated as the broker-confirmed source exit and immediately
      triggers one MARKET reversal in the stop direction.
    - A TP fill closes only that position; its stop is cancelled and there is no
      reversal from a TP.

    The local reaction target is 0.10ms. Broker/network execution latency is
    external and cannot be guaranteed by application code.
    """
    def __init__(self, execution: ExecutionAdapter, pip_size: float):
        if pip_size <= 0:
            raise ValueError("pip_size must be positive")
        self.execution = execution
        self.pip_size = pip_size
        # Keyed by each position's unique broker order id, allowing multiple
        # simultaneous XAUUSD positions with independent protection.
        self._pairs: Dict[str, VelocityPair] = {}
        self._handled_stop_fills: set[str] = set()
        self._handled_tp_fills: set[str] = set()
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
            timestamp=timestamp,
            metadata={
                "velocity_expansion": True,
                "live_bid_ask_stop": True,
                "multiple_positions": True,
                "fixed_take_profit_pips": TAKE_PROFIT_PIPS,
            },
        ))
        if result.status == "FILLED" and result.fill is not None:
            self._install_protection(result.fill, timestamp or result.fill.timestamp)
        return result

    def on_tick(self, bid: float, ask: float, timestamp: datetime, fills: list[Fill] | None = None) -> list[Fill]:
        """Track executable quotes, trail every position independently, then process fills."""
        if bid <= 0 or ask <= 0 or bid > ask:
            return fills or []
        self._last_bid = bid
        self._last_ask = ask

        # Every open position gets its own independent live trailing STOP.
        for pair in list(self._pairs.values()):
            self._trail(pair, bid, ask, timestamp)

        for fill in fills or []:
            pair = self._find_pair_for_order(fill.order_id)
            if pair is None:
                continue
            if fill.order_id == pair.stop_order_id:
                self._handle_stop_fill(pair, fill, timestamp)
            elif fill.order_id == pair.take_profit_order_id:
                self._handle_take_profit_fill(pair, fill, timestamp)
        return fills or []

    def close_all(self, timestamp: datetime, price: float | None = None) -> None:
        for position_id, pair in list(self._pairs.items()):
            self.execution.cancel_order(pair.stop_order_id)
            self.execution.cancel_order(pair.take_profit_order_id)
            self.execution.close_position(SYMBOL, timestamp, price)
            self._pairs.pop(position_id, None)

    def _find_pair_for_order(self, order_id: str) -> VelocityPair | None:
        for pair in self._pairs.values():
            if order_id in {pair.stop_order_id, pair.take_profit_order_id}:
                return pair
        return None

    def _current_stop_price(self, side: str, fallback: float) -> float:
        if side == "BUY":
            return self._last_bid if self._last_bid is not None else fallback
        return self._last_ask if self._last_ask is not None else fallback

    def _install_protection(self, fill: Fill, timestamp: datetime) -> None:
        stop_side = "SELL" if fill.side == "BUY" else "BUY"
        stop_price = self._current_stop_price(fill.side, fill.price)
        tp_price = (
            fill.price + TAKE_PROFIT_PIPS * self.pip_size
            if fill.side == "BUY"
            else fill.price - TAKE_PROFIT_PIPS * self.pip_size
        )
        stop_id = f"VEL-LIVE-STOP-{fill.order_id}"
        tp_id = f"VEL-TP130-{fill.order_id}"

        stop_result = self.execution.submit(OrderRequest(
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
        if stop_result.status != "NEW":
            raise RuntimeError(f"failed to install live bid/ask paired STOP: {stop_result.reason}")

        tp_side = "SELL" if fill.side == "BUY" else "BUY"
        tp_result = self.execution.submit(OrderRequest(
            symbol=SYMBOL, side=tp_side, quantity=fill.quantity, order_type="LIMIT",
            price=tp_price, client_order_id=tp_id, timestamp=timestamp,
            metadata={
                "paired_position_order_id": fill.order_id,
                "fixed_take_profit": True,
                "take_profit_pips": TAKE_PROFIT_PIPS,
                "entry_price": fill.price,
                "oco_stop_order_id": stop_id,
            },
        ))
        if tp_result.status != "NEW":
            self.execution.cancel_order(stop_id)
            raise RuntimeError(f"failed to install fixed 130-pip TAKE PROFIT: {tp_result.reason}")

        self._pairs[fill.order_id] = VelocityPair(
            fill.order_id, fill.side, fill.quantity, stop_id, stop_price,
            fill.price, tp_id, tp_price,
        )

    def _trail(self, pair: VelocityPair, bid: float, ask: float, timestamp: datetime) -> None:
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

    def _handle_stop_fill(self, pair: VelocityPair, fill: Fill, timestamp: datetime) -> None:
        if fill.order_id in self._handled_stop_fills:
            return
        self._handled_stop_fills.add(fill.order_id)

        # Cancel this position's TP before reversing so the old position's TP
        # cannot race with the newly opened reversal.
        self.execution.cancel_order(pair.take_profit_order_id)
        self._pairs.pop(pair.position_order_id, None)

        result = self.execution.submit(OrderRequest(
            symbol=SYMBOL, side=fill.side, quantity=fill.quantity, order_type="MARKET", price=fill.price,
            timestamp=timestamp,
            client_order_id=f"VEL-LIVE-REV-{fill.order_id}",
            metadata={
                "velocity_expansion_reversal": True,
                "trigger_stop_order_id": fill.order_id,
                "trigger_fill_price": fill.price,
                "trigger_fill_timestamp": fill.timestamp.isoformat(),
                "reaction_timestamp": timestamp.isoformat(),
                "reaction_target_ms": REACTION_TARGET_MS,
                "pocket_profit_before_reverse": True,
                "broker_confirmed_exit": True,
                "stop_at_live_executable_quote": True,
            },
        ))
        if result.status == "FILLED" and result.fill is not None:
            self._install_protection(result.fill, timestamp)

    def _handle_take_profit_fill(self, pair: VelocityPair, fill: Fill, timestamp: datetime) -> None:
        if fill.order_id in self._handled_tp_fills:
            return
        self._handled_tp_fills.add(fill.order_id)

        # TP closes only this position. Do not reverse it.
        self.execution.cancel_order(pair.stop_order_id)
        self._pairs.pop(pair.position_order_id, None)
