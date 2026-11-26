from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import timedelta

import pytest

from third_umpire import checks, hypothesis, stats, verdict
from third_umpire.flagsmith import FIXTURE_DIR, FixtureBackend, collect, fixture_hypothesis
from third_umpire.model import parse_time

PRE = hypothesis.load(fixture_hypothesis())
_CACHE = {p.stem: json.loads(p.read_text()) for p in FIXTURE_DIR.glob("*.json")}


def load(name: str) -> dict:
    return copy.deepcopy(_CACHE[name])


def entry(data: dict, suffix: str) -> dict:
    matches = [k for k in data["api"] if k.endswith(suffix)]
    assert len(matches) == 1, (suffix, matches)
    return data["api"][matches[0]]


def experiment(data: dict) -> dict:
    return data["api"][f"api/v1/environments/{data['environment_key']}/experiments/{data['experiment_id']}/"]


def payload(data: dict) -> dict:
    return entry(data, "/results/")["results"]["payload"]


def exposures(data: dict) -> dict:
    return entry(data, "/exposures/")["exposures"]["payload"]


def audit(data: dict) -> dict:
    return entry(data, "/audit/")


def metric(data: dict, metric_id: int) -> dict:
    return next(m for m in payload(data)["metrics"] if m["metric_id"] == metric_id)


def reinfer(data: dict) -> None:
    """Recompute Flagsmith's reported inference after a test edits the raw sums."""
    directions = {m["metric"]: m["direction"] for m in experiment(data)["metrics"]}
    for m in payload(data)["metrics"]:
        c = stats.VariantStats.from_api(m["variants"]["control"])
        t = stats.VariantStats.from_api(m["variants"]["near_miss"])
        inf = stats.compare(c, t, lower_is_better=directions[m["metric_id"]] == "down")
        m["inference"]["near_miss"] = None if inf is None else {
            "lift": inf.lift, "ci_low": inf.ci_low, "ci_high": inf.ci_high, "chance_to_win": inf.chance_to_win}


def set_rate(data: dict, metric_id: int, arm: str, rate: float) -> None:
    v = metric(data, metric_id)["variants"][arm]
    v["sum"] = v["sum_squares"] = float(round(v["n"] * rate))
    reinfer(data)


def started(data: dict):
    return parse_time(experiment(data)["started_at"])


def as_of(data: dict):
    return parse_time(entry(data, "/results/")["results"]["as_of"])


def cut(data: dict, fraction: float):
    s = started(data)
    return s + (as_of(data) - s) * fraction


def add_audit(data: dict, hours_after_start: float, log: str, kind: str | None, related: int | None,
              environment_id: int | None = 52011) -> None:
    when = started(data) + timedelta(hours=hours_after_start)
    env = None if environment_id is None else {"id": environment_id, "name": "x", "api_key": "k"}
    row = {"id": 99000 + len(audit(data)["results"]), "created_date": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
           "log": log, "author": {"email": "tester@example.com"}, "environment": env,
           "related_object_id": related, "related_object_type": kind}
    audit(data)["results"].insert(0, row)


@dataclass
class Review:
    ctx: checks.Context
    checks: dict[str, checks.Check]
    verdict: verdict.Verdict
    backend: FixtureBackend

    def status(self, check_id: str) -> str:
        return self.checks[check_id].status


def run_review(data: dict, pre=PRE) -> Review:
    backend = FixtureBackend(data, name=data.get("name", "test"))
    snap = collect(backend, backend.environment_key, backend.experiment_id)
    ctx = checks.build_context(snap, pre, None if pre else "missing")
    results = checks.run_all(ctx)
    return Review(ctx, {c.id: c for c in results}, verdict.decide(results, ctx), backend)


@pytest.fixture
def healthy() -> dict:
    return load("healthy")


@pytest.fixture
def bad() -> dict:
    return load("bad-peeking")


@pytest.fixture
def early() -> dict:
    return load("keep-running")
