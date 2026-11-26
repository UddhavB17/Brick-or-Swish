"""A local stand-in for the Flagsmith Admin API, serving one fixture.

It exists so the real ``flagsmith`` CLI can be exercised end to end without an
account: point the CLI at it with ``--api-url`` and the host-scoped key variable
the CLI reads for a non-default host (``FLAGSMITH_API_KEY_127_0_0_1_<port>``).
Reads return the fixture's recorded responses; ``POST .../complete/`` applies
the same state change Flagsmith does.
"""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEMO_KEY = "mock.third-umpire-demo"


def scoped_key_var(host: str, port: int) -> str:
    return f"FLAGSMITH_API_KEY_{host.replace('-', '__').replace('.', '_')}_{port}"


class MockFlagsmith:
    def __init__(self, fixture: dict[str, Any], api_key: str = DEMO_KEY):
        self.api = copy.deepcopy(fixture["api"])
        self.env_key = fixture["environment_key"]
        self.experiment_id = int(fixture["experiment_id"])
        self.api_key = api_key
        self.requests: list[tuple[str, str, int]] = []
        self.lock = threading.Lock()

    @property
    def experiment_path(self) -> str:
        return f"api/v1/environments/{self.env_key}/experiments/{self.experiment_id}/"

    def handle(self, method: str, raw_path: str, auth: str | None, body: bytes) -> tuple[int, Any]:
        path = raw_path.lstrip("/").split("?", 1)[0]
        if auth != f"Api-Key {self.api_key}":
            return 401, {"detail": "Authentication credentials were not provided."}
        with self.lock:
            if method == "GET":
                if path in self.api:
                    return 200, self.api[path]
                return 404, {"detail": "Not found."}
            if method == "POST" and path == f"{self.experiment_path}complete/":
                return self._complete(body)
        return 405, {"detail": f'Method "{method}" not allowed.'}

    def _complete(self, body: bytes) -> tuple[int, Any]:
        try:
            data = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return 400, {"detail": "JSON parse error"}
        experiment = self.api[self.experiment_path]
        if experiment["status"] not in ("running", "paused"):
            return 400, {"detail": f"Cannot complete an experiment that is {experiment['status']}."}
        decision = data.get("rollout_decision")
        option_ids = [o["id"] for o in experiment["feature"]["multivariate_options"]]
        if decision not in ("control", "variant", "disable"):
            return 400, {"rollout_decision": ["Must be one of control, variant, disable."]}
        if decision == "variant" and data.get("rollout_variant") not in option_ids:
            return 400, {"rollout_variant": ["Must be one of the feature's multivariate options."]}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        experiment.update(status="completed", ended_at=now, rollout_decision=decision,
                          rollout_variant=data.get("rollout_variant"), experiment_rollout=None)
        if decision == "variant":
            for option in experiment["feature"]["multivariate_options"]:
                option["default_percentage_allocation"] = 100.0 if option["id"] == data["rollout_variant"] else 0.0
        return 200, experiment


def serve(fixture: dict[str, Any], host: str = "127.0.0.1", port: int = 0,
          api_key: str = DEMO_KEY, quiet: bool = True) -> tuple[ThreadingHTTPServer, MockFlagsmith]:
    mock = MockFlagsmith(fixture, api_key)

    class Handler(BaseHTTPRequestHandler):
        def _respond(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            status, payload = mock.handle(method, self.path, self.headers.get("Authorization"), body)
            mock.requests.append((method, self.path, status))
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._respond("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._respond("POST")

        def log_message(self, fmt: str, *args: Any) -> None:
            if not quiet:
                super().log_message(fmt, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    return server, mock
