from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from .models import Tick, SYMBOL


@dataclass(frozen=True)
class MetaApiCredentials:
    account_id: str
    token: str


class MetaApiClient(Protocol):
    async def connect(self, credentials: MetaApiCredentials) -> None: ...
    async def ticks(self, symbol: str) -> AsyncIterator[Tick]: ...
    async def account_balance(self) -> float: ...
    async def symbol_pip_value(self, symbol: str) -> float: ...
    async def close(self) -> None: ...


class MetaApiWebsocketAdapter:
    """Adapter boundary for the real MetaAPI websocket SDK.

    The application owns the lifecycle and credentials; the concrete SDK
    implementation is injected here so strategy logic stays broker-neutral.
    """

    def __init__(self, client: MetaApiClient):
        self.client = client
        self.credentials: MetaApiCredentials | None = None

    async def connect(self, account_id: str, token: str) -> None:
        self.credentials = MetaApiCredentials(account_id, token)
        await self.client.connect(self.credentials)

    async def stream_xauusd(self) -> AsyncIterator[Tick]:
        async for tick in self.client.ticks(SYMBOL):
            yield tick

    async def balance(self) -> float:
        return await self.client.account_balance()

    async def pip_value(self) -> float:
        return await self.client.symbol_pip_value(SYMBOL)

    async def close(self) -> None:
        await self.client.close()
