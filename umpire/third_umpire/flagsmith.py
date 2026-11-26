"""Talks to Flagsmith through the official CLI (``flagsmith api``), or replays a fixture.

Every read goes through ``flagsmith api <path> --jq <projection>`` so the CLI
handles credentials (``flagsmith login`` or ``FLAGSMITH_API_KEY``) and only the
fields the checks use come back. The one write is
``POST .../experiments/<id>/complete/``, which ends the experiment and serves
the chosen variation to 100% of the environment.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import AuditEntry, Environment, Experiment, Exposures, Results, Snapshot, parse_metric_defs, parse_time
from .tokens import Ledger

JQ_ENVIRONMENT = "{id, name, api_key, project}"
JQ_EXPERIMENT = (
    "{id, name, status, hypothesis, created_at, started_at, ended_at, rollout_decision, rollout_variant,"
    " feature: {id: .feature.id, name: .feature.name, multivariate_options:"
    " [.feature.multivariate_options[]? | {id, key, string_value, default_percentage_allocation}]},"
    " metrics: [.metrics[]? | {metric, metric_name, aggregation, direction, expected_direction}],"
    " experiment_rollout: (.experiment_rollout | if . == null then null"
    " else {rollout_percentage, multivariate_feature_state_values} end)}"
)
JQ_EXPERIMENT_LIST = "[(.results? // .)[] | {id, name, status, started_at, feature: .feature.name}]"
JQ_METRICS = "[(.results? // .)[] | {id, name, aggregation, direction, event: .definition.event}]"
JQ_EXPOSURES = ".exposures | if . == null then null else {as_of, is_final, payload} end"
JQ_RESULTS = ".results | if . == null then null else {as_of, is_final, payload} end"
JQ_AUDIT = (
    "{next, results: [.results[] | {id, created_date, log, related_object_type, related_object_id,"
    " environment: (.environment.id // null), author: (.author.email // null)}]}"
)
JQ_COMPLETED = "{id, status, ended_at, rollout_decision, rollout_variant}"

AUDIT_PAGE_SIZE = 100
AUDIT_MAX_PAGES = 10


class FlagsmithError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


def experiments_path(env_key: str) -> str:
    return f"api/v1/environments/{env_key}/experiments/"


class FlagsmithCLI:
    """Runs the real ``flagsmith`` binary."""

    writes_are_simulated = False

    def __init__(self, binary: str | None = None, api_url: str | None = None, ledger: Ledger | None = None):
        self.binary = binary or os.environ.get("FLAGSMITH_BIN") or shutil.which("flagsmith") or _home_bin()
        if not self.binary:
            raise FlagsmithError(
                "Flagsmith CLI not found. Install it: curl -fsSL https://get.flagsmith.com | sh",
            )
        self.api_url = api_url
        self.ledger = ledger
        self.label = "Flagsmith CLI"

    def version(self) -> str:
        proc = subprocess.run([self.binary, "--version"], capture_output=True, text=True, timeout=30)
        return proc.stdout.strip()

    def command(self, path: str, *, method: str = "GET", jq: str | None = None, body: bool = False) -> list[str]:
        cmd = [self.binary, "api", path, "--no-input"]
        if method != "GET":
            cmd += ["-X", method]
        if body:
            cmd += ["--input", "-"]
        if jq:
            cmd += ["--jq", jq]
        if self.api_url:
            cmd += ["--api-url", self.api_url]
        return cmd

    def _run(self, path: str, *, method: str = "GET", jq: str | None = None, body: Any = None) -> Any:
        cmd = self.command(path, method=method, jq=jq, body=body is not None)
        proc = subprocess.run(
            cmd,
            input=json.dumps(body) if body is not None else None,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if self.ledger is not None:
            self.ledger.record("flagsmith-cli", f"{method} {path}", proc.stdout)
        if proc.returncode != 0:
            raise _cli_error(method, path, proc.stderr)
        out = proc.stdout.strip()
        if not out:
            return None
        lines = out.splitlines()
        try:
            return json.loads(out) if len(lines) == 1 else [json.loads(line) for line in lines]
        except json.JSONDecodeError as exc:
            raise FlagsmithError(f"{method} {path}: CLI output is not JSON", detail=out[:300]) from exc

    def get(self, path: str, jq: str | None = None) -> Any:
        return self._run(path, jq=jq)

    def post(self, path: str, body: Any = None, jq: str | None = None) -> Any:
        return self._run(path, method="POST", jq=jq, body=body if body is not None else {})

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def _home_bin() -> str | None:
    candidate = Path.home() / ".local" / "bin" / "flagsmith"
    return str(candidate) if candidate.exists() else None


def _cli_error(method: str, path: str, stderr: str) -> FlagsmithError:
    status = None
    for token in stderr.split():
        if token.isdigit() and len(token) == 3:
            status = int(token)
    detail = stderr.strip()
    first = detail.splitlines()[-1] if detail else "no output"
    return FlagsmithError(f"flagsmith api {method} {path} failed: {first}", status=status, detail=detail)


class FixtureBackend:
    """Serves a recorded snapshot of the API responses; writes are only recorded."""

    writes_are_simulated = True

    def __init__(self, data: dict[str, Any], ledger: Ledger | None = None, name: str = "fixture"):
        self.data = data
        self.api = data["api"]
        self.ledger = ledger
        self.writes: list[tuple[str, Any]] = []
        self.label = f"fixture '{name}'"
        self.environment_key: str = data["environment_key"]
        self.experiment_id: int = int(data["experiment_id"])

    @classmethod
    def load(cls, name_or_path: str, ledger: Ledger | None = None) -> FixtureBackend:
        path = resolve_fixture(name_or_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data, ledger=ledger, name=path.stem)

    def get(self, path: str, jq: str | None = None) -> Any:
        key = path.split("?", 1)[0]
        if key not in self.api:
            raise FlagsmithError(f"GET {path} returned 404 Not Found", status=404)
        value = self.api[key]
        if isinstance(value, dict) and value.get("__status__"):
            raise FlagsmithError(f"GET {path} returned {value['__status__']}", status=int(value["__status__"]),
                                 detail=json.dumps(value.get("body", {})))
        if self.ledger is not None:
            self.ledger.record("flagsmith-cli", f"GET {key}", json.dumps(value, separators=(",", ":")))
        return copy.deepcopy(value)

    def post(self, path: str, body: Any = None, jq: str | None = None) -> Any:
        self.writes.append((path, body))
        return {"simulated": True, "path": path, "body": body}

    def now(self) -> datetime:
        return parse_time(self.data["now"])


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def resolve_fixture(name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate
    packaged = FIXTURE_DIR / f"{name_or_path}.json"
    if packaged.is_file():
        return packaged
    names = ", ".join(sorted(p.stem for p in FIXTURE_DIR.glob("*.json")))
    raise FlagsmithError(f"no fixture '{name_or_path}' (packaged fixtures: {names})")


def fixture_hypothesis() -> Path:
    return FIXTURE_DIR / "HYPOTHESIS.md"


def list_experiments(backend: Any, env_key: str) -> list[dict[str, Any]]:
    return backend.get(experiments_path(env_key), jq=JQ_EXPERIMENT_LIST) or []


def fetch_experiment(backend: Any, env_key: str, experiment_id: int) -> Experiment:
    metric_defs = parse_metric_defs(backend.get(f"api/v1/environments/{env_key}/experiment-metrics/", jq=JQ_METRICS))
    raw = backend.get(f"{experiments_path(env_key)}{experiment_id}/", jq=JQ_EXPERIMENT)
    return Experiment.parse(raw, metric_defs)


def _audit_since(backend: Any, project: int, since: datetime | None) -> list[AuditEntry]:
    entries: list[AuditEntry] = []
    for page in range(1, AUDIT_MAX_PAGES + 1):
        raw = backend.get(f"api/v1/projects/{project}/audit/?page_size={AUDIT_PAGE_SIZE}&page={page}", jq=JQ_AUDIT)
        batch = [AuditEntry.parse(r) for r in (raw or {}).get("results", [])]
        entries.extend(batch)
        if not raw or not raw.get("next") or not batch:
            break
        if since and min(e.created_date for e in batch) < since:
            break
    return entries


def collect(backend: Any, env_key: str, experiment_id: int) -> Snapshot:
    environment = Environment.parse(backend.get(f"api/v1/environments/{env_key}/", jq=JQ_ENVIRONMENT))
    experiment = fetch_experiment(backend, env_key, experiment_id)
    base = f"{experiments_path(env_key)}{experiment_id}/"
    exposures = Exposures.parse(_optional(backend, f"{base}exposures/", JQ_EXPOSURES))
    results = Results.parse(_optional(backend, f"{base}results/", JQ_RESULTS))
    audit: list[AuditEntry] | None
    audit_error = None
    try:
        audit = _audit_since(backend, environment.project, experiment.started_at)
    except FlagsmithError as exc:
        audit, audit_error = None, str(exc)
    return Snapshot(
        environment=environment,
        experiment=experiment,
        results=results,
        exposures=exposures,
        audit=audit,
        audit_error=audit_error,
        now=backend.now(),
        source=backend.label,
    )


def _optional(backend: Any, path: str, jq: str) -> Any:
    try:
        return backend.get(path, jq=jq)
    except FlagsmithError as exc:
        if exc.status == 404:
            return None
        raise


def complete(backend: Any, env_key: str, experiment_id: int, body: dict[str, Any]) -> Any:
    return backend.post(f"{experiments_path(env_key)}{experiment_id}/complete/", body, jq=JQ_COMPLETED)


__all__ = [
    "FlagsmithCLI",
    "FixtureBackend",
    "FlagsmithError",
    "collect",
    "complete",
    "fetch_experiment",
    "fixture_hypothesis",
    "list_experiments",
]
