"""Typed views over the Flagsmith Experimentation API payloads.

Parsers accept either the raw API response or the leaner ``--jq`` projection the
umpire asks the CLI for; the projections keep the API's own field names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .stats import Inference, VariantStats

CONTROL = "control"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _results(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and "results" in raw and isinstance(raw["results"], list):
        return raw["results"]
    return list(raw or [])


@dataclass(frozen=True)
class Environment:
    id: int
    name: str
    api_key: str
    project: int

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Environment:
        project = raw.get("project")
        if isinstance(project, dict):
            project = project.get("id")
        return cls(id=int(raw["id"]), name=str(raw["name"]), api_key=str(raw["api_key"]), project=int(project))

    @property
    def looks_like_production(self) -> bool:
        return "prod" in self.name.lower()


@dataclass(frozen=True)
class VariantOption:
    id: int
    key: str | None
    value: str | None
    default_percentage_allocation: float


@dataclass(frozen=True)
class ExperimentMetric:
    metric_id: int
    name: str
    aggregation: str
    direction: str
    expected_direction: str | None
    event: str | None = None

    @property
    def lower_is_better(self) -> bool:
        return self.direction == "down"


@dataclass(frozen=True)
class Experiment:
    id: int
    name: str
    status: str
    hypothesis: str
    feature_id: int
    feature_name: str
    options: list[VariantOption]
    metrics: list[ExperimentMetric]
    rollout_percentage: float | None
    allocations: dict[int, float] | None
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    rollout_decision: str | None = None
    rollout_variant: int | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any], metric_defs: dict[int, dict[str, Any]] | None = None) -> Experiment:
        feature = raw.get("feature") or {}
        options = [
            VariantOption(
                id=int(o["id"]),
                key=o.get("key"),
                value=o.get("string_value") if o.get("string_value") is not None else o.get("value"),
                default_percentage_allocation=float(o.get("default_percentage_allocation") or 0),
            )
            for o in feature.get("multivariate_options") or []
        ]
        metric_defs = metric_defs or {}
        metrics = []
        for m in raw.get("metrics") or []:
            metric_id = int(m["metric"])
            definition = metric_defs.get(metric_id, {})
            metrics.append(
                ExperimentMetric(
                    metric_id=metric_id,
                    name=str(m.get("metric_name") or definition.get("name") or metric_id),
                    aggregation=str(m.get("aggregation") or definition.get("aggregation") or ""),
                    direction=str(m.get("direction") or definition.get("direction") or "up"),
                    expected_direction=m.get("expected_direction"),
                    event=definition.get("event"),
                )
            )
        rollout = raw.get("experiment_rollout")
        allocations = None
        rollout_percentage = None
        if rollout:
            rollout_percentage = float(rollout.get("rollout_percentage") or 0)
            allocations = {
                int(v["multivariate_feature_option"]): float(v["percentage_allocation"])
                for v in rollout.get("multivariate_feature_state_values") or []
            }
        return cls(
            id=int(raw["id"]),
            name=str(raw.get("name") or ""),
            status=str(raw.get("status") or ""),
            hypothesis=str(raw.get("hypothesis") or ""),
            feature_id=int(feature.get("id") or 0),
            feature_name=str(feature.get("name") or ""),
            options=options,
            metrics=metrics,
            rollout_percentage=rollout_percentage,
            allocations=allocations,
            created_at=parse_time(raw.get("created_at")),
            started_at=parse_time(raw.get("started_at")),
            ended_at=parse_time(raw.get("ended_at")),
            rollout_decision=raw.get("rollout_decision"),
            rollout_variant=raw.get("rollout_variant"),
        )

    def option_by_key(self, key: str) -> VariantOption | None:
        return next((o for o in self.options if o.key == key), None)

    def expected_shares(self) -> tuple[dict[str, float] | None, str]:
        """The split exposures should follow, and where it came from.

        The experiment's rollout override is the split identities are actually
        bucketed by. Flagsmith's own SRM check reads the environment default
        instead, which is 0% per variant when the experiment sets the split."""
        if self.allocations:
            source = "experiment rollout"
            weights = {o.key: self.allocations.get(o.id, 0.0) for o in self.options if o.key}
        else:
            source = "environment default"
            weights = {o.key: o.default_percentage_allocation for o in self.options if o.key}
        allocated = sum(weights.values())
        if not weights or allocated <= 0 or allocated > 100:
            return None, source
        shares = {CONTROL: (100 - allocated) / 100}
        shares.update({k: w / 100 for k, w in weights.items() if w > 0})
        return shares, source


@dataclass(frozen=True)
class Point:
    bucket: datetime
    values: dict[str, int]


def _points(series: dict[str, Any] | None, field_name: str) -> list[Point]:
    if not series:
        return []
    points = [
        Point(bucket=parse_time(p["bucket"]), values={k: int(v) for k, v in (p.get(field_name) or {}).items()})
        for p in series.get("points") or []
    ]
    return sorted(points, key=lambda p: p.bucket)


@dataclass(frozen=True)
class MetricResult:
    metric_id: int
    variants: dict[str, VariantStats]
    inference: dict[str, Inference | None]
    conversions: list[Point] | None


@dataclass(frozen=True)
class Results:
    as_of: datetime | None
    is_final: bool
    srm_p_value: float | None
    metrics: list[MetricResult]
    exposures: list[Point]
    granularity: str | None

    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> Results | None:
        if raw is None:
            return None
        if "results" in raw:
            raw = raw["results"]
        if not raw or not raw.get("payload"):
            return None
        payload = raw["payload"]
        metrics = []
        for m in payload.get("metrics") or []:
            conv = m.get("conversions_timeseries")
            metrics.append(
                MetricResult(
                    metric_id=int(m["metric_id"]),
                    variants={k: VariantStats.from_api(v) for k, v in (m.get("variants") or {}).items()},
                    inference={k: Inference.from_api(v) for k, v in (m.get("inference") or {}).items()},
                    conversions=_points(conv, "converted_identities") if conv else None,
                )
            )
        exp_series = payload.get("exposures_timeseries") or {}
        return cls(
            as_of=parse_time(raw.get("as_of")),
            is_final=bool(raw.get("is_final")),
            srm_p_value=payload.get("srm_p_value"),
            metrics=metrics,
            exposures=_points(exp_series, "new_identities"),
            granularity=exp_series.get("granularity"),
        )

    def metric(self, metric_id: int) -> MetricResult | None:
        return next((m for m in self.metrics if m.metric_id == metric_id), None)


@dataclass(frozen=True)
class Exposures:
    as_of: datetime | None
    excluded_identities: int
    timeseries: list[Point]

    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> Exposures | None:
        if raw is None:
            return None
        if "exposures" in raw:
            raw = raw["exposures"]
        if not raw or not raw.get("payload"):
            return None
        payload = raw["payload"]
        return cls(
            as_of=parse_time(raw.get("as_of")),
            excluded_identities=int(payload.get("excluded_identities") or 0),
            timeseries=_points(payload.get("timeseries"), "new_identities"),
        )


@dataclass(frozen=True)
class AuditEntry:
    id: int
    created_date: datetime
    log: str
    related_object_type: str | None
    related_object_id: int | None
    environment: int | None
    author: str | None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> AuditEntry:
        author = raw.get("author")
        if isinstance(author, dict):
            author = author.get("email")
        environment = raw.get("environment")
        if isinstance(environment, dict):
            environment = environment.get("id")
        return cls(
            id=int(raw["id"]),
            created_date=parse_time(raw["created_date"]),
            log=str(raw.get("log") or ""),
            related_object_type=raw.get("related_object_type"),
            related_object_id=raw.get("related_object_id"),
            environment=environment,
            author=author,
        )


@dataclass
class Snapshot:
    """Everything one review reads, fetched once."""

    environment: Environment
    experiment: Experiment
    results: Results | None
    exposures: Exposures | None
    audit: list[AuditEntry] | None
    audit_error: str | None
    now: datetime
    source: str
    notes: list[str] = field(default_factory=list)

    @property
    def data_time(self) -> datetime:
        if self.results and self.results.as_of:
            return self.results.as_of
        return self.now


def parse_metric_defs(raw: Any) -> dict[int, dict[str, Any]]:
    defs = {}
    for m in _results(raw):
        definition = m.get("definition") or {}
        defs[int(m["id"])] = {
            "name": m.get("name"),
            "aggregation": m.get("aggregation"),
            "direction": m.get("direction"),
            "event": m.get("event") or definition.get("event"),
        }
    return defs
