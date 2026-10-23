"""Read-only client for Home Assistant's REST API. Everything stays on the LAN."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any


class HAError(Exception):
    """Home Assistant could not be reached, or refused, or had no usable data."""


class HAClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise HAError(f"Home Assistant returned HTTP {exc.code} for {path}") from None
        except (OSError, ValueError) as exc:
            raise HAError(f"Home Assistant unreachable at {self.base_url}: {exc}") from None

    def ping(self) -> None:
        self._get("/api/")

    def state(self, entity_id: str) -> str:
        data = self._get(f"/api/states/{urllib.parse.quote(entity_id)}")
        return str(data["state"])

    def numeric_history(self, entity_id: str, hours: int) -> list[float]:
        """Numeric states for the last `hours`, oldest first."""
        start = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        path = (
            f"/api/history/period/{urllib.parse.quote(start)}"
            f"?filter_entity_id={urllib.parse.quote(entity_id)}&minimal_response&no_attributes"
        )
        series = self._get(path)
        values: list[float] = []
        for entry in (series[0] if series else []):
            try:
                values.append(float(entry["state"]))
            except (KeyError, TypeError, ValueError):
                continue  # skip unavailable and unknown states
        return values


def client_from_store(store) -> HAClient | None:
    """Build a client from the URL and token saved in the web page. None if not set."""
    url = store.get_setting("ha_url") or ""
    token = store.get_setting("ha_token") or ""
    return HAClient(url, token) if url and token else None
