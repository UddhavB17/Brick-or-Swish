"""Generates the planted fixtures as raw Flagsmith API responses.

Each scenario simulates identities hour by hour (exposure time, first-conversion
time, guardrail and shot count), then builds the payloads the way Flagsmith
does: per-variant n/sum/sum_squares, inference from the same delta-method maths,
and hourly time series bucketed by first exposure and first conversion. Seeds
are fixed, so re-running reproduces the committed files exactly.

    python tools/build_fixtures.py
"""

from __future__ import annotations

import json
import math
import random
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from third_umpire import stats  # noqa: E402

OUT = ROOT / "third_umpire" / "fixtures"
HOUR = timedelta(hours=1)
UTC = timezone.utc

ENV_KEY = "bos7fYq2LkPz9mWcR4tXvH"
ENV_ID, DEV_ENV_ID, PROJECT_ID = 52011, 52010, 18842
FEATURE_ID, AA_FEATURE_ID, OPTION_ID = 140233, 140234, 77815
EXPERIMENT_ID, AA_EXPERIMENT_ID = 412, 411
PRIMARY, GUARDRAIL, SHOTS = 901, 902, 903
EXPERIMENT_NAME = "Near-miss feedback vs plain miss"
OWNER = {"id": 3301, "email": "uddhav@brickorswish.dev", "first_name": "Uddhav", "last_name": "B",
         "last_login": "2026-11-26T07:55:00Z", "uuid": "6d3f8e1a-31c4-4b8e-9d55-0d2b7c9e4a10"}
TEAMMATE = {"id": 3307, "email": "sam@brickorswish.dev", "first_name": "Sam", "last_name": "K",
            "last_login": "2026-11-26T11:20:00Z", "uuid": "a7c2e9b0-5f14-4c3a-8e61-2b9d0f7e5c33"}


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def floor_hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


@dataclass
class Scenario:
    name: str
    title: str
    seed: int
    started_at: datetime
    as_of: datetime
    now: datetime
    rate_per_hour: float
    treatment_share: Callable[[datetime], float]
    conversion: Callable[[str, float], float]
    quit_rate: dict[str, float]
    shots_mean: dict[str, float]
    excluded_identities: int = 0
    configured_treatment_share: float = 50.0
    extra_audit: list[dict] = field(default_factory=list)
    conversion_cutoff: datetime | None = None


def simulate(s: Scenario) -> dict:
    rng = random.Random(s.seed)
    runtime = (s.as_of - s.started_at).total_seconds()
    identities = []
    bucket = floor_hour(s.started_at)
    while bucket <= s.as_of:
        lo, hi = max(bucket, s.started_at), min(bucket + HOUR, s.as_of)
        width = (hi - lo).total_seconds() / 3600
        arrivals = max(0, round(rng.gauss(s.rate_per_hour * width, math.sqrt(s.rate_per_hour * width))))
        for _ in range(arrivals):
            t = lo + (hi - lo) * rng.random()
            arm = "near_miss" if rng.random() < s.treatment_share(t) else "control"
            identities.append((arm, t))
        bucket += HOUR

    arms = ("control", "near_miss")
    sums = {m: {a: [0, 0.0, 0.0] for a in arms} for m in (PRIMARY, GUARDRAIL, SHOTS)}
    exp_points: dict[datetime, dict[str, int]] = {}
    conv_points = {PRIMARY: {}, GUARDRAIL: {}}

    def bump(points: dict, when: datetime, arm: str) -> None:
        slot = points.setdefault(floor_hour(when), {a: 0 for a in arms})
        slot[arm] += 1

    for arm, t in identities:
        frac = (t - s.started_at).total_seconds() / runtime
        bump(exp_points, t, arm)
        converted = False
        if rng.random() < s.conversion(arm, frac):
            when = t + timedelta(hours=rng.expovariate(1 / 0.5))
            if when <= s.as_of and (s.conversion_cutoff is None or when < s.conversion_cutoff):
                converted = True
                bump(conv_points[PRIMARY], when, arm)
        quit_ = False
        if rng.random() < s.quit_rate[arm]:
            when = t + timedelta(seconds=rng.uniform(2, 10))
            if when <= s.as_of and (s.conversion_cutoff is None or when < s.conversion_cutoff):
                quit_ = True
                bump(conv_points[GUARDRAIL], when, arm)
        shots = max(1, round(rng.gauss(s.shots_mean[arm], 4)))
        for metric, value in ((PRIMARY, float(converted)), (GUARDRAIL, float(quit_)), (SHOTS, float(shots))):
            acc = sums[metric][arm]
            acc[0] += 1
            acc[1] += value
            acc[2] += value * value

    def series(points: dict, field_name: str) -> dict:
        ordered = sorted(points)
        return {"granularity": "hour",
                "points": [{"bucket": iso(b), field_name: points[b]} for b in ordered]}

    metrics = []
    for metric, direction, aggregation in ((PRIMARY, "up", "occurrence"), (GUARDRAIL, "down", "occurrence"),
                                           (SHOTS, "informational", "mean")):
        variants = {a: {"n": v[0], "sum": v[1], "sum_squares": v[2]} for a, v in sums[metric].items()}
        c, t = (stats.VariantStats(*sums[metric][a]) for a in arms)
        gated = min(c.n, t.n) < 50 or (aggregation == "occurrence" and min(c.sum, t.sum) < 5)
        inf = None if gated else stats.compare(c, t, lower_is_better=direction == "down")
        metrics.append({
            "metric_id": metric,
            "variants": variants,
            "inference": {"near_miss": None if inf is None else {
                "lift": inf.lift, "ci_low": inf.ci_low, "ci_high": inf.ci_high, "chance_to_win": inf.chance_to_win}},
            "conversions_timeseries": series(conv_points[metric], "converted_identities")
            if metric in conv_points else None,
        })

    exposures_ts = series(exp_points, "new_identities")
    return {
        "results": {
            "as_of": iso(s.as_of),
            "last_error_at": None,
            "refresh_requested_at": iso(s.as_of - timedelta(minutes=3)),
            "is_final": False,
            # Flagsmith tests SRM against the environment default split, which is
            # 0% per variation when the experiment rollout sets the split.
            "payload": {"srm_p_value": None, "metrics": metrics, "exposures_timeseries": exposures_ts},
        }
    }, {
        "exposures": {
            "as_of": iso(s.as_of),
            "last_error_at": None,
            "refresh_requested_at": iso(s.as_of - timedelta(minutes=3)),
            "is_final": False,
            "payload": {"excluded_identities": s.excluded_identities, "timeseries": exposures_ts},
        }
    }


def environment() -> dict:
    return {"id": ENV_ID, "uuid": "0c4b7a52-8f1e-4d2a-9b3c-5e6f7a8b9c0d", "name": "Production",
            "api_key": ENV_KEY, "description": "Real players only", "project": PROJECT_ID,
            "minimum_change_request_approvals": None, "allow_client_traits": True, "banner_text": None,
            "banner_colour": None, "hide_disabled_flags": None, "use_identity_composite_key_for_hashing": True,
            "hide_sensitive_data": False, "use_mv_v2_evaluation": True,
            "use_identity_overrides_in_local_eval": False, "is_creating": False, "metadata": []}


def experiment(s: Scenario) -> dict:
    return {
        "id": EXPERIMENT_ID,
        "feature": {
            "id": FEATURE_ID, "name": "miss_feedback", "type": "MULTIVARIATE", "initial_value": "control",
            "multivariate_options": [{
                "id": OPTION_ID, "uuid": "3e9a1c7d-2b4f-4e8a-a1d3-7c5b9e0f2a64", "type": "unicode",
                "integer_value": None, "string_value": "near_miss", "boolean_value": None,
                "default_percentage_allocation": 0.0, "key": "near_miss"}],
        },
        "name": EXPERIMENT_NAME,
        "hypothesis": ("Showing near-miss feedback (exact timing error + ghost replay) after a missed shot increases "
                       "the share of players who start a second round."),
        "status": "running",
        "metrics": [
            {"id": 1201, "metric": PRIMARY, "metric_name": "Second round started", "aggregation": "occurrence",
             "direction": "up", "expected_direction": "increase", "created_at": iso(s.started_at - 5 * timedelta(minutes=1))},
            {"id": 1202, "metric": GUARDRAIL, "metric_name": "Quit within 10s of first miss",
             "aggregation": "occurrence", "direction": "down", "expected_direction": "not_increase",
             "created_at": iso(s.started_at - 5 * timedelta(minutes=1))},
            {"id": 1203, "metric": SHOTS, "metric_name": "Shots per session", "aggregation": "mean",
             "direction": "informational", "expected_direction": "not_decrease",
             "created_at": iso(s.started_at - 5 * timedelta(minutes=1))},
        ],
        "experiment_rollout": {
            "enabled": True, "rollout_percentage": 100.0,
            "feature_state_value": {"type": "unicode", "value": "control"},
            "multivariate_feature_state_values": [
                {"multivariate_feature_option": OPTION_ID, "percentage_allocation": s.configured_treatment_share}],
            "audience": {"match": "all", "segments": []},
        },
        "created_at": iso(s.started_at - timedelta(minutes=5)),
        "updated_at": iso(s.started_at),
        "started_at": iso(s.started_at),
        "ended_at": None,
        "rollout_decision": None,
        "rollout_variant": None,
    }


def metric_defs() -> list[dict]:
    rows = [(PRIMARY, "Second round started", "occurrence", "up", "second_round_started"),
            (GUARDRAIL, "Quit within 10s of first miss", "occurrence", "down", "quit_within_10s"),
            (SHOTS, "Shots per session", "mean", "informational", "shots_taken")]
    return [{"id": i, "name": n, "description": "", "aggregation": a, "direction": d,
             "definition": {"version": 1, "event": e}, "experiments": [EXPERIMENT_ID],
             "created_at": "2026-11-26T08:10:00.000Z", "updated_at": "2026-11-26T08:10:00.000Z"}
            for i, n, a, d, e in rows]


def audit_entry(id_: int, when: datetime, log: str, kind: str | None, related: int | None,
                env_id: int | None, author: dict | None = OWNER) -> dict:
    env = None
    if env_id is not None:
        env = {"id": env_id, "name": "Production" if env_id == ENV_ID else "Development",
               "api_key": ENV_KEY if env_id == ENV_ID else "devK3yZ8wQ1rT5yU7iO9pA"}
    return {"id": id_, "created_date": iso(when), "log": log, "author": author,
            "organisation": {"id": 9001, "name": "Brick or Swish"}, "environment": env,
            "project": {"id": PROJECT_ID, "name": "Brick or Swish"}, "related_object_id": related,
            "related_object_uuid": None, "related_object_type": kind, "is_system_event": False}


def audit(s: Scenario) -> dict:
    start = s.started_at
    entries = [
        (datetime(2026, 11, 26, 8, 2, tzinfo=UTC), "New Flag / Remote Config created: miss_feedback", "FEATURE", FEATURE_ID, None),
        (datetime(2026, 11, 26, 8, 3, tzinfo=UTC), "Flag / Remote Config updated: miss_feedback", "FEATURE", FEATURE_ID, None),
        (datetime(2026, 11, 26, 8, 10, tzinfo=UTC), "Metric 'Second round started' created", "METRIC", PRIMARY, ENV_ID),
        (datetime(2026, 11, 26, 8, 10, 20, tzinfo=UTC), "Metric 'Quit within 10s of first miss' created", "METRIC", GUARDRAIL, ENV_ID),
        (datetime(2026, 11, 26, 8, 10, 40, tzinfo=UTC), "Metric 'Shots per session' created", "METRIC", SHOTS, ENV_ID),
        (datetime(2026, 11, 26, 8, 20, tzinfo=UTC), "Experiment 'A/A sanity check' created for environment Production", "EXPERIMENT", AA_EXPERIMENT_ID, ENV_ID),
        (datetime(2026, 11, 26, 8, 21, tzinfo=UTC), "Experiment 'A/A sanity check' running for environment Production", "EXPERIMENT", AA_EXPERIMENT_ID, ENV_ID),
        (datetime(2026, 11, 26, 9, 18, tzinfo=UTC), "Experiment 'A/A sanity check' completed for environment Production", "EXPERIMENT", AA_EXPERIMENT_ID, ENV_ID),
        (start - timedelta(minutes=5), f"Experiment '{EXPERIMENT_NAME}' created for environment Production", "EXPERIMENT", EXPERIMENT_ID, ENV_ID),
        (start, f"Experiment '{EXPERIMENT_NAME}' running for environment Production", "EXPERIMENT", EXPERIMENT_ID, ENV_ID),
        (start + timedelta(seconds=1), f"Experiment '{EXPERIMENT_NAME}' rollout set to 100.0% of all identities", "EXPERIMENT", EXPERIMENT_ID, ENV_ID),
        (start + timedelta(hours=10, minutes=44), "Flag state updated for feature: aa_sanity_check", "FEATURE_STATE", AA_FEATURE_ID, DEV_ENV_ID),
    ]
    rows = [audit_entry(5000 + i, when, log, kind, rel, env) for i, (when, log, kind, rel, env) in enumerate(entries)]
    rows += s.extra_audit
    rows = [r for r in rows if r["created_date"] <= iso(s.now)]
    rows.sort(key=lambda r: r["created_date"], reverse=True)
    return {"count": len(rows), "next": None, "previous": None, "results": rows}


def experiment_list(s: Scenario) -> dict:
    aa = {"id": AA_EXPERIMENT_ID, "name": "A/A sanity check", "status": "completed",
          "started_at": "2026-11-26T08:21:00.000Z", "feature": {"id": AA_FEATURE_ID, "name": "aa_sanity_check"}}
    main = experiment(s)
    return {"count": 2, "next": None, "previous": None, "results": [main, aa]}


def build(s: Scenario) -> dict:
    results, exposures = simulate(s)
    base = f"api/v1/environments/{ENV_KEY}/"
    exp_base = f"{base}experiments/{EXPERIMENT_ID}/"
    return {
        "name": s.name,
        "title": s.title,
        "now": iso(s.now),
        "environment_key": ENV_KEY,
        "experiment_id": EXPERIMENT_ID,
        "api": {
            base: environment(),
            f"{base}experiments/": experiment_list(s),
            exp_base: experiment(s),
            f"{base}experiment-metrics/": metric_defs(),
            f"{exp_base}exposures/": exposures,
            f"{exp_base}results/": results,
            f"api/v1/projects/{PROJECT_ID}/audit/": audit(s),
        },
    }


START = datetime(2026, 11, 26, 9, 30, tzinfo=UTC)


def steady(control: float, treatment: float) -> Callable[[str, float], float]:
    return lambda arm, frac: treatment if arm == "near_miss" else control


def bad_split(t: datetime) -> float:
    edited, restored = START + timedelta(hours=2, minutes=10), START + timedelta(hours=5, minutes=35)
    return 0.8 if edited <= t < restored else 0.5


def fading(arm: str, frac: float) -> float:
    if arm == "control":
        return 0.31
    return 0.60 if frac < 0.5 else 0.30


def bad_audit() -> list[dict]:
    t = START
    return [
        audit_entry(6001, t + timedelta(hours=2, minutes=8), f"Experiment '{EXPERIMENT_NAME}' updated for environment Production", "EXPERIMENT", EXPERIMENT_ID, ENV_ID, TEAMMATE),
        audit_entry(6002, t + timedelta(hours=2, minutes=10), f"Experiment '{EXPERIMENT_NAME}' rollout set to 100.0% of all identities", "EXPERIMENT", EXPERIMENT_ID, ENV_ID, TEAMMATE),
        audit_entry(6003, t + timedelta(hours=5, minutes=35), f"Experiment '{EXPERIMENT_NAME}' rollout set to 100.0% of all identities", "EXPERIMENT", EXPERIMENT_ID, ENV_ID, TEAMMATE),
        audit_entry(6004, t + timedelta(hours=6, minutes=50), "Metric 'Second round started' updated", "METRIC", PRIMARY, ENV_ID, TEAMMATE),
    ]


SCENARIOS = [
    Scenario(
        name="bad-peeking",
        title="99% chance to win after 9 hours, with the split edited mid-test",
        seed=7,
        started_at=START,
        as_of=START + timedelta(hours=9, minutes=15),
        now=START + timedelta(hours=9, minutes=21),
        rate_per_hour=62,
        treatment_share=bad_split,
        conversion=fading,
        quit_rate={"control": 0.21, "near_miss": 0.23},
        shots_mean={"control": 9.0, "near_miss": 10.1},
        excluded_identities=37,
        extra_audit=bad_audit(),
    ),
    Scenario(
        name="healthy",
        title="30 hours, 50/50, pre-registered sample reached, clean audit log",
        seed=1,
        started_at=START,
        as_of=START + timedelta(hours=30),
        now=START + timedelta(hours=30, minutes=12),
        rate_per_hour=29,
        treatment_share=lambda t: 0.5,
        conversion=steady(0.35, 0.45),
        quit_rate={"control": 0.22, "near_miss": 0.20},
        shots_mean={"control": 9.1, "near_miss": 10.3},
    ),
    Scenario(
        name="keep-running",
        title="Clean so far, but only 14 hours and about 240 per arm",
        seed=1,
        started_at=START,
        as_of=START + timedelta(hours=14),
        now=START + timedelta(hours=14, minutes=6),
        rate_per_hour=34,
        treatment_share=lambda t: 0.5,
        conversion=steady(0.35, 0.44),
        quit_rate={"control": 0.22, "near_miss": 0.21},
        shots_mean={"control": 9.1, "near_miss": 10.0},
    ),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SCENARIOS:
        path = OUT / f"{s.name}.json"
        path.write_text(json.dumps(build(s), indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    shutil.copyfile(ROOT.parent / "HYPOTHESIS.md", OUT / "HYPOTHESIS.md")
    print(f"copied HYPOTHESIS.md into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
