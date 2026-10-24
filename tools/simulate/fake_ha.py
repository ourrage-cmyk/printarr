"""A small stand-in for Home Assistant's REST API, for simulation only.

It answers the three calls printarr makes (GET /api/, GET /api/states/<id>, and
GET /api/history/period/<start>), so entity values and sparklines can be tested without
a real Home Assistant. Values are fixed per entity; history is a deterministic wave.
It only accepts the simulation token below, which is not a real credential.

    python tools/simulate/fake_ha.py [--port 8123]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIM_TOKEN = "simulation-token-not-real"
FIXTURES = Path(__file__).with_name("fixtures") / "ha_states.json"


def load_states() -> dict[str, dict]:
    return {row["entity_id"]: row for row in json.loads(FIXTURES.read_text())}


def history_for(entity_id: str, base: float, amp: float, start: datetime) -> list[dict]:
    """Hourly points from `start` to now. Deterministic per entity, so reruns match."""
    seed = int(hashlib.sha256(entity_id.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    points = []
    now = datetime.now(UTC)
    t = start.replace(minute=0, second=0, microsecond=0)
    hour = 0
    while t <= now:
        value = base + amp * math.sin(hour / 5.0 + seed * 6.28) + amp * 0.3 * math.sin(hour / 1.7)
        points.append({"state": f"{value:.1f}", "last_changed": t.isoformat()})
        t += timedelta(hours=1)
        hour += 1
    return points


class Handler(BaseHTTPRequestHandler):
    states: dict[str, dict] = {}

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        return

    def _send(self, code: int, body: object) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.headers.get("Authorization") != f"Bearer {SIM_TOKEN}":
            self._send(401, {"message": "401: Unauthorized"})
            return
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        if path == "/api/":
            self._send(200, {"message": "API running."})
            return
        match = re.fullmatch(r"/api/states/([^/]+)", path)
        if match:
            row = self.states.get(match.group(1))
            if row is None:
                self._send(404, {"message": "Entity not found."})
            else:
                self._send(200, row)
            return
        if path.startswith("/api/history/period/"):
            query = urllib.parse.parse_qs(parsed.query)
            entity = query.get("filter_entity_id", [""])[0]
            row = self.states.get(entity)
            if row is None:
                self._send(200, [[]])
                return
            start_text = path.rsplit("/", 1)[-1].replace(" ", "+")
            try:
                start = datetime.fromisoformat(start_text)
            except ValueError:
                start = datetime.now(UTC) - timedelta(hours=24)
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            spec = row.get("simulation", {"base": 10, "amp": 2})
            self._send(200, [history_for(entity, spec["base"], spec["amp"], start)])
            return
        self._send(404, {"message": "Not found"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()
    Handler.states = load_states()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fake Home Assistant on http://{args.host}:{args.port}  (token: {SIM_TOKEN})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
