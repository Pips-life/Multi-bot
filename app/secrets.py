from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CredentialStore:
    """Small local persistence boundary for one-time account setup.

    Production deployments should replace this with encrypted server-side
    storage/secret management. Never expose the token to the browser after
    initial submission or commit it to the repository.
    """

    def __init__(self, path: str = "data/account.json"):
        self.path = Path(path)

    def save(self, account_id: str, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"account_id": account_id, "token": token}), encoding="utf-8")

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
