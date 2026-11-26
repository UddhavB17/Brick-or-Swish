"""The deterministic checks. Each one reads the snapshot, returns PASS, WARN or
FAIL, and says why with numbers. Nothing here calls a model.

Kinds decide how the verdict treats a FAIL:
  validity  - the data can't be trusted, so no decision can be made from it
  readiness - the data is fine but the pre-registered sample or runtime isn't reached
  decision  - the data is fine and ready, and the pre-registered rule says no
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import stats
from .hypothesis import PreRegistration
from .model import CONTROL, ExperimentMetric, MetricResult, Point, Snapshot
from .stats import Inference

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
VALIDITY, READINESS, DECISION = "validity", "readiness", "decision"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}

LAUNCH_GRACE = timedelta(minutes=2)
SRM_MIN_TOTAL = 100
SRM_WARN_P = 0.01
DUAL_EXPOSURE_FAIL_RATE = 0.01
INFERENCE_TOLERANCE = 0.01
TAIL_MIN_EXPOSURES = 20
WIRING_MIN_EXPECTED = 10
WIRING_WARN_RATIO = 0.25
NOVELTY_MIN_PER_HALF = 30
NOVELTY_WARN_RATIO = 0.5
GUARDRAIL_WARN_CHANCE = 0.8


@dataclass
class Check:
    id: str
    title: str
    kind: str
    status: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "kind": self.kind, "title": self.title,
                "summary": self.summary, "evidence": self.evidence}


def worst(statuses: Iterable[str]) -> str:
    return max(statuses, key=_RANK.__getitem__, default=PASS)


def pct(x: float | None, signed: bool = False, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"


def p_value(p: float) -> str:
    return f"{p:.1e}" if p < 0.001 else f"{p:.3f}"


def when(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC") if t else "n/a"


def hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


# ---------------------------------------------------------------- context


@dataclass
class Context:
    snap: Snapshot
    pre: PreRegistration | None
    pre_error: str | None
    shares: dict[str, float] | None
    shares_source: str
    primary: ExperimentMetric | None
    primary_result: MetricResult | None
    treatment: str | None
    counts: dict[str, int]
    guardrails: list[ExperimentMetric]
    exposure_series: list[Point]

    @property
    def arms(self) -> list[str]:
        if self.shares:
            return list(self.shares)
        keys = [CONTROL] + [o.key for o in self.snap.experiment.options if o.key]
        return list(dict.fromkeys(keys))

    def reported(self, metric: ExperimentMetric | None, variant: str | None) -> Inference | None:
        if not metric or not variant or not self.snap.results:
            return None
        result = self.snap.results.metric(metric.metric_id)
        return result.inference.get(variant) if result else None

    def recomputed(self, metric: ExperimentMetric | None, variant: str | None) -> Inference | None:
        if not metric or not variant or not self.snap.results:
            return None
        result = self.snap.results.metric(metric.metric_id)
        if not result or CONTROL not in result.variants or variant not in result.variants:
            return None
        return stats.compare(result.variants[CONTROL], result.variants[variant],
                             lower_is_better=metric.lower_is_better)

    def inference(self, metric: ExperimentMetric | None, variant: str | None) -> Inference | None:
        return self.reported(metric, variant) or self.recomputed(metric, variant)


def build_context(snap: Snapshot, pre: PreRegistration | None, pre_error: str | None = None) -> Context:
    exp = snap.experiment
    shares, source = exp.expected_shares()
    primary = exp.metrics[0] if exp.metrics else None
    primary_result = snap.results.metric(primary.metric_id) if (primary and snap.results) else None

    counts: dict[str, int] = {}
    if primary_result and primary_result.variants:
        counts = {k: v.n for k, v in primary_result.variants.items()}
    exposure_series = (snap.results.exposures if snap.results else []) or (
        snap.exposures.timeseries if snap.exposures else []
    )
    if not counts:
        for point in exposure_series:
            for k, v in point.values.items():
                counts[k] = counts.get(k, 0) + v

    guardrail_events = set(pre.guardrail_events) if pre else set()
    if guardrail_events and any(m.event for m in exp.metrics):
        guardrails = [m for m in exp.metrics[1:] if m.event in guardrail_events]
    else:
        guardrails = [m for m in exp.metrics[1:] if m.direction == "down" or m.expected_direction == "not_increase"]

    candidates = [k for k in (shares or {}) if k != CONTROL] or [o.key for o in exp.options if o.key]
    ctx = Context(snap, pre, pre_error, shares, source, primary, primary_result, None, counts, guardrails,
                  exposure_series)

    def chance(key: str) -> float:
        inf = ctx.inference(primary, key)
        return inf.chance_to_win if inf else -1.0

    ctx.treatment = max(candidates, key=chance) if candidates else None
    return ctx


# ---------------------------------------------------------------- helpers


def _totals(points: list[Point], until: datetime | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in points:
        if until is None or p.bucket < until:
            for k, v in p.values.items():
                out[k] = out.get(k, 0) + v
    return out


def _span(ctx: Context) -> tuple[datetime | None, datetime]:
    start = ctx.snap.experiment.started_at
    series = ctx.exposure_series
    if start is None and series:
        start = series[0].bucket
    return start, ctx.snap.data_time


def _cut(ctx: Context, fraction: float) -> datetime | None:
    start, end = _span(ctx)
    if start is None:
        return None
    return start + (end - start) * fraction


def _split_label(shares: dict[str, float]) -> str:
    return " / ".join(f"{k} {v * 100:g}%" for k, v in shares.items())


def _counts_label(counts: dict[str, int], keys: Iterable[str]) -> str:
    total = sum(counts.get(k, 0) for k in keys) or 1
    return ", ".join(f"{k} {counts.get(k, 0):,} ({counts.get(k, 0) / total:.1%})" for k in keys)


def _interval(inf: Inference) -> str:
    return f"{pct(inf.lift, True)} (95% interval {pct(inf.ci_low, True)} to {pct(inf.ci_high, True)})"


# ---------------------------------------------------------------- validity


def check_preregistration(ctx: Context) -> Check:
    c = Check("preregistration", "Pre-registration on file", VALIDITY, PASS, "")
    pre, exp = ctx.pre, ctx.snap.experiment
    if pre is None:
        c.status = FAIL
        c.summary = "No readable pre-registration, so there is no rule to judge the result against."
        c.evidence.append(ctx.pre_error or "HYPOTHESIS.md not found")
        return c
    c.evidence.append(f"{pre.path} (sha256 {pre.sha256[:12]})")
    problems, cautions = [], []
    if pre.registered_on and exp.started_at and pre.registered_on > exp.started_at.date():
        problems.append(f"registered {pre.registered_on}, after the experiment started ({when(exp.started_at)})")
    elif pre.registered_on:
        c.evidence.append(f"Registered {pre.registered_on}, launch {when(exp.started_at)}")
    if ctx.primary and ctx.primary.event and pre.primary_event and ctx.primary.event != pre.primary_event:
        problems.append(
            f"primary metric is '{ctx.primary.event}' in Flagsmith but '{pre.primary_event}' in the pre-registration"
        )
    elif ctx.primary and not ctx.primary.event:
        cautions.append(f"couldn't read the event behind primary metric '{ctx.primary.name}'")
    else:
        c.evidence.append(f"Primary metric matches: {pre.primary_event}")
    if ctx.shares and len(ctx.shares) == 2:
        configured = round(ctx.shares.get(CONTROL, 0) * 100)
        if configured != pre.split["control"]:
            problems.append(
                f"pre-registered split {pre.split['control']}/{pre.split['treatment']}, "
                f"configured {_split_label(ctx.shares)}"
            )
    if pre.amendments:
        cautions.append(f"{len(pre.amendments)} amendment(s) recorded: " + "; ".join(pre.amendments)[:200])
    if problems:
        c.status = FAIL
        c.summary = "The pre-registration doesn't match the experiment: " + "; ".join(problems) + "."
    elif cautions:
        c.status = WARN
        c.summary = "Pre-registration found, with caveats: " + "; ".join(cautions) + "."
    else:
        c.summary = "Hypothesis, metrics and split were fixed before launch and match the experiment."
    c.evidence.extend(problems + cautions)
    return c


def check_srm(ctx: Context) -> Check:
    c = Check("srm", "Traffic split matches the configuration", VALIDITY, PASS, "")
    exp, results = ctx.snap.experiment, ctx.snap.results
    alpha = ctx.pre.srm_alpha if ctx.pre else 0.001
    if not ctx.shares:
        c.status, c.summary = WARN, "No usable split is configured, so the split can't be tested."
        return c
    total = sum(ctx.counts.get(k, 0) for k in ctx.shares)
    rollout = f", {exp.rollout_percentage:g}% of identities enrolled" if exp.rollout_percentage is not None else ""
    c.evidence.append(f"Configured: {_split_label(ctx.shares)} ({ctx.shares_source}{rollout})")
    c.evidence.append(f"Observed: {_counts_label(ctx.counts, ctx.shares)}")
    reported = results.srm_p_value if results else None
    if total < SRM_MIN_TOTAL:
        c.status = WARN
        c.summary = f"Only {total} exposed identities; the split can't be tested below {SRM_MIN_TOTAL}."
        return c
    test = stats.srm(ctx.counts, ctx.shares)
    assert test is not None
    c.data = {"p_value": test.p_value, "statistic": test.statistic, "reported_p_value": reported}
    c.evidence.append(f"Chi-squared {test.statistic:.1f}, p = {p_value(test.p_value)} (invalid below p < {alpha:g})")
    if reported is None:
        c.evidence.append(
            "Flagsmith reported no SRM p-value: it tests the environment default split, which is 0% per variation "
            "when the experiment sets the split, so its dashboard would not have warned."
        )
    else:
        c.evidence.append(f"Flagsmith's own SRM p-value: {p_value(reported)}")
    lowest = min(test.p_value, reported if reported is not None else 1.0)
    if lowest < alpha:
        c.status = FAIL
        c.summary = (
            f"Sample ratio mismatch: {_counts_label(ctx.counts, ctx.shares)} against {_split_label(ctx.shares)} "
            f"(p = {p_value(lowest)}). Assignment or exposure logging is broken, so the result is invalid."
        )
    elif lowest < SRM_WARN_P:
        c.status = WARN
        c.summary = f"The split is drifting from {_split_label(ctx.shares)} (p = {p_value(lowest)}); watch it."
    else:
        c.summary = f"Exposures follow the configured {_split_label(ctx.shares)} split (p = {p_value(lowest)})."
    return c


def check_one_sided(ctx: Context) -> Check:
    c = Check("one_sided", "Exposures arrive in every arm", VALIDITY, PASS, "")
    arms = ctx.arms
    totals = {k: ctx.counts.get(k, 0) for k in arms}
    c.evidence.append("Exposed identities: " + ", ".join(f"{k} {v:,}" for k, v in totals.items()))
    unknown = sorted(set(ctx.counts) - set(arms))
    if sum(totals.values()) == 0:
        c.status, c.summary = WARN, "No exposures recorded yet."
        return c
    empty = [k for k, v in totals.items() if v == 0]
    if empty:
        c.status = FAIL
        c.summary = f"No exposures at all for {', '.join(empty)}: that arm is never served or never logged."
        return c
    cut = _cut(ctx, 2 / 3)
    series = ctx.exposure_series
    if cut and series:
        tail = {k: sum(p.values.get(k, 0) for p in series if p.bucket >= cut) for k in arms}
        c.evidence.append(f"Since {when(cut)}: " + ", ".join(f"{k} +{v:,}" for k, v in tail.items()))
        stalled = [k for k, v in tail.items() if v == 0]
        if stalled and max(tail.values()) >= TAIL_MIN_EXPOSURES:
            last_seen = {
                k: max((p.bucket for p in series if p.values.get(k, 0) > 0), default=None) for k in stalled
            }
            c.status = FAIL
            c.summary = (
                "Exposures stopped arriving on "
                + ", ".join(f"{k} (last at {when(t)})" for k, t in last_seen.items())
                + " while the other arm kept growing."
            )
            return c
    if unknown:
        c.status = WARN
        c.summary = f"Exposures logged for variants that aren't in the split: {', '.join(unknown)}."
        return c
    c.summary = "Every arm received exposures, all the way to the latest data."
    return c


def check_dual_exposure(ctx: Context) -> Check:
    c = Check("dual_exposure", "Nobody saw both variants", VALIDITY, PASS, "")
    if ctx.snap.exposures is None:
        c.status, c.summary = WARN, "Exposures haven't been computed yet, so cross-exposure can't be checked."
        return c
    excluded = ctx.snap.exposures.excluded_identities
    total = sum(ctx.counts.values()) + excluded
    rate = excluded / total if total else 0.0
    c.data = {"excluded": excluded, "rate": rate}
    c.evidence.append(
        f"{excluded:,} of {total:,} identities ({rate:.1%}) were exposed to more than one variant; "
        "Flagsmith quarantines them from results"
    )
    if excluded == 0:
        c.summary = "No identity was exposed to more than one variant."
    elif rate <= DUAL_EXPOSURE_FAIL_RATE:
        c.status = WARN
        c.summary = f"{excluded:,} identities ({rate:.1%}) saw both variants; small, but worth knowing."
    else:
        c.status = FAIL
        c.summary = (
            f"{excluded:,} identities ({rate:.1%}) saw both variants. Assignment changed under people, "
            "usually because the split or rollout was edited mid-test."
        )
    return c


def check_conversion_wiring(ctx: Context) -> Check:
    c = Check("conversion_wiring", "Conversions keep pace with exposures", VALIDITY, PASS, "")
    results = ctx.snap.results
    if not results or not ctx.primary_result:
        c.status, c.summary = WARN, "No results yet, so conversion tracking can't be checked."
        return c
    metrics = [m for m in [ctx.primary, *ctx.guardrails] if m]
    statuses, summaries = [], []
    cut = _cut(ctx, 2 / 3)
    exposures = ctx.exposure_series
    for metric in metrics:
        result = results.metric(metric.metric_id)
        if not result:
            continue
        name = metric.event or metric.name
        exposed = sum(v.n for v in result.variants.values())
        converted = sum(v.sum for v in result.variants.values())
        if metric.aggregation == "occurrence" and exposed >= SRM_MIN_TOTAL and converted == 0:
            statuses.append(FAIL)
            summaries.append(f"'{name}' has zero conversions across {exposed:,} exposed identities")
            c.evidence.append(f"{name}: 0 conversions from {exposed:,} exposed. Check the event name and identify().")
            continue
        if not result.conversions or not exposures or not cut:
            c.evidence.append(f"{name}: {int(converted):,} conversions from {exposed:,} exposed")
            continue
        e_before = sum(_totals(exposures, cut).values())
        c_before = sum(_totals(result.conversions, cut).values())
        e_tail = sum(_totals(exposures).values()) - e_before
        c_tail = sum(_totals(result.conversions).values()) - c_before
        rate = stats.proportion(c_before, e_before)
        expected = rate * e_tail
        c.evidence.append(
            f"{name}: {c_before:,} conversions per {e_before:,} exposures before {when(cut)} ({rate:.1%}); "
            f"since then +{c_tail:,} per +{e_tail:,} (about {expected:.0f} expected)"
        )
        if expected >= WIRING_MIN_EXPECTED and c_tail == 0:
            statuses.append(FAIL)
            summaries.append(f"'{name}' conversions flatlined after {when(cut)} while {e_tail:,} new identities arrived")
        elif expected >= WIRING_MIN_EXPECTED and c_tail < WIRING_WARN_RATIO * expected:
            statuses.append(WARN)
            summaries.append(f"'{name}' conversions dropped to {c_tail} against about {expected:.0f} expected")
        else:
            statuses.append(PASS)
    c.status = worst(statuses)
    if c.status == PASS:
        c.summary = "Conversions keep arriving in step with new exposures."
    elif c.status == FAIL:
        c.summary = "Broken conversion wiring: " + "; ".join(summaries) + "."
    else:
        c.summary = "Conversion tracking looks weak: " + "; ".join(summaries) + "."
    return c


def _audit_relevant(ctx: Context) -> list[tuple[str, Any]]:
    """Entries after launch that touch the flag, the experiment or its metrics, with a severity."""
    exp, env = ctx.snap.experiment, ctx.snap.environment
    metric_ids = {m.metric_id for m in exp.metrics}
    start = exp.started_at
    end = exp.ended_at or ctx.snap.now
    out = []
    for entry in ctx.snap.audit or []:
        if start is None or entry.created_date <= start + LAUNCH_GRACE or entry.created_date > end:
            continue
        if entry.environment not in (None, env.id):
            continue
        kind = (entry.related_object_type or "").upper().replace(" ", "_")
        log = entry.log
        if kind == "EXPERIMENT" and entry.related_object_id == exp.id:
            if log.rstrip().endswith(f"completed for environment {env.name}"):
                continue
            if " paused " in f" {log} " or " running for environment" in log:
                out.append((WARN, entry))
            else:
                out.append((FAIL, entry))
        elif kind in ("FEATURE", "FEATURE_STATE", "EF_VERSION") and entry.related_object_id == exp.feature_id:
            out.append((FAIL, entry))
        elif kind == "METRIC" and entry.related_object_id in metric_ids:
            out.append((FAIL, entry))
        elif exp.feature_name and (f": {exp.feature_name}" in log or f"'{exp.feature_name}'" in log):
            out.append((FAIL, entry))
    return out


def check_audit(ctx: Context) -> Check:
    c = Check("audit", "No edits after launch", VALIDITY, PASS, "")
    exp = ctx.snap.experiment
    if ctx.snap.audit is None:
        c.status = WARN
        c.summary = "The audit log couldn't be read, so post-launch edits can't be ruled out."
        c.evidence.append(ctx.snap.audit_error or "audit log unavailable")
        return c
    if exp.started_at is None:
        c.status, c.summary = WARN, "The experiment hasn't started, so there is no launch to compare against."
        return c
    hits = _audit_relevant(ctx)
    since = [e for e in ctx.snap.audit if e.created_date > exp.started_at]
    c.evidence.append(f"{len(since)} audit entries in the project since launch at {when(exp.started_at)}")
    for severity, entry in hits:
        hours_in = hours(entry.created_date - exp.started_at)
        c.evidence.append(
            f"{severity} {when(entry.created_date)} ({hours_in:.1f} h in) by {entry.author or 'an API key'}: {entry.log}"
        )
    c.data = {"edits": len([h for h in hits if h[0] == FAIL]), "pauses": len([h for h in hits if h[0] == WARN])}
    c.status = worst(s for s, _ in hits)
    if c.status == FAIL:
        c.summary = (
            f"{c.data['edits']} edit(s) to {exp.feature_name or 'the flag'}, the experiment or its metrics after "
            "launch. Pre-registration rule 7 forbids mid-test edits: end it and start a new one."
        )
    elif c.status == WARN:
        c.summary = "The experiment was paused or resumed after launch; the rest of the setup was left alone."
    else:
        c.summary = f"Nothing touched {exp.feature_name}, the experiment or its metrics after launch."
    return c


# ---------------------------------------------------------------- readiness


def check_sample_size(ctx: Context) -> Check:
    c = Check("sample_size", "Pre-registered sample size and runtime", READINESS, PASS, "")
    pre, exp = ctx.pre, ctx.snap.experiment
    if pre is None:
        c.status, c.summary = FAIL, "No pre-registered sample size to compare against."
        return c
    start, end = _span(ctx)
    runtime = hours(end - start) if start else 0.0
    arms = ctx.arms
    smallest = min((ctx.counts.get(k, 0) for k in arms), default=0)
    hard_stop_passed = bool(pre.hard_stop and ctx.snap.now > pre.hard_stop)
    sample_ok = smallest >= pre.min_per_arm
    runtime_ok = runtime >= pre.min_hours
    c.data = {"runtime_hours": runtime, "smallest_arm": smallest, "met": sample_ok and runtime_ok,
              "hard_stop_passed": hard_stop_passed}
    c.evidence.append(
        "Per arm: " + ", ".join(f"{k} {ctx.counts.get(k, 0):,}/{pre.min_per_arm}" for k in arms)
        + f"; runtime {runtime:.1f} h of {pre.min_hours:g} h (results as of {when(end)})"
    )
    if pre.hard_stop:
        c.evidence.append(f"Hard stop {when(pre.hard_stop.astimezone(end.tzinfo))}"
                          + (" has passed" if hard_stop_passed else ""))
    if sample_ok and runtime_ok:
        c.summary = f"Both conditions met: at least {pre.min_per_arm} per arm and {runtime:.0f} h of runtime."
        return c
    c.status = FAIL
    gaps = []
    if not sample_ok:
        gaps.append(f"smallest arm has {smallest:,} of {pre.min_per_arm} identities")
    if not runtime_ok:
        gaps.append(f"{runtime:.1f} of {pre.min_hours:g} hours")
    if hard_stop_passed:
        c.summary = "Underpowered at the hard stop (" + ", ".join(gaps) + "): rule 5 says nothing ships."
    else:
        c.summary = "Too early to decide (" + ", ".join(gaps) + "). Reading the result now is peeking."
    return c


# ---------------------------------------------------------------- decision


def check_interval(ctx: Context) -> Check:
    c = Check("interval", "Credible interval clears zero", DECISION, PASS, "")
    metric, key = ctx.primary, ctx.treatment
    reported, recomputed = ctx.reported(metric, key), ctx.recomputed(metric, key)
    inf = reported or recomputed
    if not metric or not key or inf is None:
        c.status = WARN
        c.summary = "No interval yet: Flagsmith shows 'Collecting data' until each arm has 50 identities and 5 conversions."
        return c
    label = metric.event or metric.name
    c.evidence.append(f"{key} vs control on {label}: {_interval(inf)}, chance to beat control {pct(inf.chance_to_win)}")
    if reported and recomputed:
        drift = stats.max_abs_diff(
            [reported.lift, reported.ci_low, reported.ci_high, reported.chance_to_win],
            [recomputed.lift, recomputed.ci_low, recomputed.ci_high, recomputed.chance_to_win],
        )
        if drift > INFERENCE_TOLERANCE:
            c.status = WARN
            c.evidence.append(f"Recomputed from the raw sums: {_interval(recomputed)}; differs by {drift * 100:.1f} pp")
        else:
            c.evidence.append("Recomputed from Flagsmith's raw per-variant sums: matches")
    elif recomputed and not reported:
        c.evidence.append("Flagsmith reported no inference yet; this is recomputed from the raw sums")
    c.data = {"lift": inf.lift, "ci_low": inf.ci_low, "ci_high": inf.ci_high, "chance_to_win": inf.chance_to_win}
    favourable = inf.ci_high < 0 if metric.lower_is_better else inf.ci_low > 0
    unfavourable = inf.ci_low > 0 if metric.lower_is_better else inf.ci_high < 0
    if favourable:
        c.summary = c.summary or f"The whole 95% interval for {key} is on the winning side of zero."
        if c.status == WARN:
            c.summary = "The interval clears zero, but Flagsmith's numbers don't reproduce from its own sums."
    elif unfavourable:
        c.status = FAIL
        c.summary = f"{key} is credibly worse than control on {label}."
    else:
        c.status = WARN
        c.summary = f"The 95% interval ({pct(inf.ci_low, True)} to {pct(inf.ci_high, True)}) still includes no effect."
    return c


def check_guardrail(ctx: Context) -> Check:
    c = Check("guardrail", "Guardrail not credibly worse", DECISION, PASS, "")
    key = ctx.treatment
    expected = set(ctx.pre.guardrail_events) if ctx.pre else set()
    attached = {m.event for m in ctx.guardrails if m.event}
    missing = sorted(expected - attached)
    if not ctx.guardrails:
        c.status = WARN
        c.summary = "No guardrail metric is attached to the experiment" + (
            f" ({', '.join(missing)} is pre-registered)." if missing else "."
        )
        return c
    statuses, worse = [], []
    for metric in ctx.guardrails:
        inf = ctx.inference(metric, key)
        name = metric.event or metric.name
        if inf is None:
            statuses.append(WARN)
            c.evidence.append(f"{name}: not enough data yet")
            continue
        # A guardrail fails when its interval sits entirely on the harmful side of zero.
        harmful_up = metric.lower_is_better or metric.expected_direction == "not_increase"
        credibly_worse = inf.ci_low > 0 if harmful_up else inf.ci_high < 0
        p_up = 1 - inf.chance_to_win if metric.lower_is_better else inf.chance_to_win
        chance_worse = p_up if harmful_up else 1 - p_up
        c.evidence.append(f"{name}: {_interval(inf)}; chance it got worse {pct(chance_worse)}")
        if credibly_worse:
            statuses.append(FAIL)
            worse.append(f"{name} {pct(inf.lift, True)}")
        elif chance_worse >= GUARDRAIL_WARN_CHANCE:
            statuses.append(WARN)
        else:
            statuses.append(PASS)
    if missing:
        statuses.append(WARN)
        c.evidence.append(f"Pre-registered but not attached: {', '.join(missing)}")
    c.status = worst(statuses)
    c.data = {"credibly_worse": bool(worse)}
    if c.status == FAIL:
        c.summary = f"Guardrail credibly worse ({', '.join(worse)}): rule 3 says keep control whatever the primary says."
    elif c.status == WARN:
        c.summary = "The guardrail leans worse or lacks data, but isn't credibly worse."
    else:
        c.summary = "The guardrail is not credibly worse."
    return c


def check_novelty(ctx: Context) -> Check:
    c = Check("novelty", "Effect holds early vs late", DECISION, PASS, "")
    key, result = ctx.treatment, ctx.primary_result
    series = ctx.exposure_series
    mid = _cut(ctx, 1 / 2)
    if not key or not result or not result.conversions or not series or mid is None:
        c.status, c.summary = WARN, "No conversion time series yet, so early and late can't be compared."
        return c
    e_early, c_early = _totals(series, mid), _totals(result.conversions, mid)
    e_all, c_all = _totals(series), _totals(result.conversions)
    halves = {}
    for arm in (CONTROL, key):
        e1, c1 = e_early.get(arm, 0), c_early.get(arm, 0)
        e2, c2 = e_all.get(arm, 0) - e1, c_all.get(arm, 0) - c1
        halves[arm] = (e1, c1, e2, c2)
    if min(min(h[0], h[2]) for h in halves.values()) < NOVELTY_MIN_PER_HALF:
        c.status = WARN
        c.summary = f"Too few identities per half (need {NOVELTY_MIN_PER_HALF} per arm) to compare early and late."
        return c
    early = stats.relative_lift(*(stats.proportion(halves[a][1], halves[a][0]) for a in (CONTROL, key)))
    late = stats.relative_lift(*(stats.proportion(halves[a][3], halves[a][2]) for a in (CONTROL, key)))
    c.data = {"early_lift": early, "late_lift": late}
    for label, i in (("first half", 0), ("second half", 2)):
        c.evidence.append(
            f"{label}: "
            + ", ".join(f"{a} {halves[a][i + 1]}/{halves[a][i]} ({stats.proportion(halves[a][i + 1], halves[a][i]):.1%})"
                        for a in (CONTROL, key))
        )
    c.evidence.append(f"Lift {pct(early, True)} before {when(mid)}, {pct(late, True)} after "
                      "(from running totals; conversions are bucketed by first conversion)")
    if early is None or late is None:
        c.status, c.summary = WARN, "Control has no conversions in one half, so lift can't be split."
    elif early > 0 and late <= 0:
        c.status = FAIL
        c.summary = f"Novelty effect: {pct(early, True)} lift early, {pct(late, True)} late. The win is wearing off."
    elif early > 0 and late < NOVELTY_WARN_RATIO * early:
        c.status = WARN
        c.summary = f"The lift is shrinking ({pct(early, True)} early, {pct(late, True)} late); possible novelty."
    else:
        c.summary = f"The effect holds: {pct(early, True)} early, {pct(late, True)} late."
    return c


def check_stopping_rule(ctx: Context, sample: Check, guardrail: Check) -> Check:
    c = Check("stopping_rule", "Pre-registered decision rule", DECISION, PASS, "")
    pre, key = ctx.pre, ctx.treatment
    inf = ctx.inference(ctx.primary, key)
    if pre is None or key is None:
        c.status, c.summary = FAIL, "No pre-registered rule to apply."
        return c
    if inf is None:
        c.status, c.summary = FAIL, "No chance-to-beat-control figure yet, so the rule can't be applied."
        return c
    chance = inf.chance_to_win
    c.data = {"chance_to_win": chance, "rule": None}
    c.evidence.append(
        f"Chance {key} beats control: {pct(chance)} (ship at >= {pct(pre.ship_chance, digits=0)}, "
        f"keep control at <= {pct(pre.keep_chance, digits=0)})"
    )
    if not sample.data.get("met"):
        c.status = FAIL
        if sample.data.get("hard_stop_passed"):
            c.data["rule"] = 5
            c.summary = "Rule 5: the hard stop passed before the sample size was reached. Report as underpowered."
        else:
            c.data["rule"] = 1
            c.summary = f"Rule 1: no decision before the sample size and runtime are reached, even at {pct(chance)}."
    elif guardrail.data.get("credibly_worse"):
        c.status, c.data["rule"] = FAIL, 3
        c.summary = "Rule 3: the guardrail is credibly worse, so keep control."
    elif chance >= pre.ship_chance:
        c.data["rule"] = 2
        c.summary = f"Rule 2: ship {key} ({pct(chance)} chance to beat control, guardrail not credibly worse)."
    elif chance <= pre.keep_chance:
        c.status, c.data["rule"] = FAIL, 3
        c.summary = f"Rule 3: keep control ({key} has only {pct(chance)} chance to beat it)."
    else:
        c.status, c.data["rule"] = FAIL, 4
        c.summary = f"Rule 4: inconclusive at {pct(chance)}. Keep control and report it as inconclusive."
    return c


def run_all(ctx: Context) -> list[Check]:
    sample = check_sample_size(ctx)
    guardrail = check_guardrail(ctx)
    return [
        check_preregistration(ctx),
        check_srm(ctx),
        check_one_sided(ctx),
        check_dual_exposure(ctx),
        check_conversion_wiring(ctx),
        check_audit(ctx),
        sample,
        check_interval(ctx),
        guardrail,
        check_novelty(ctx),
        check_stopping_rule(ctx, sample, guardrail),
    ]
