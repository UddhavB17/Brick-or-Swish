"""Turns check results into SHIP, DON'T SHIP or KEEP RUNNING. Pure rules, in order."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .checks import DECISION, FAIL, READINESS, VALIDITY, WARN, Check, Context

SHIP = "SHIP"
DONT_SHIP = "DON'T SHIP"
KEEP_RUNNING = "KEEP RUNNING"


@dataclass
class RolloutPlan:
    environment_name: str
    environment_id: int
    environment_key: str
    production: bool
    experiment_id: int
    experiment_name: str
    feature_name: str
    variant_key: str
    variant_option_id: int
    path: str
    body: dict[str, Any]
    before: str
    after: str

    @property
    def confirm_phrase(self) -> str:
        return f"ship {self.variant_key} to 100% in {self.environment_name}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment_name,
            "production": self.production,
            "flag": self.feature_name,
            "variant": self.variant_key,
            "request": f"POST {self.path}",
            "body": self.body,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class Verdict:
    call: str
    headline: str
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)
    winner: str | None = None
    plan: RolloutPlan | None = None

    @property
    def exit_code(self) -> int:
        return {SHIP: 0, DONT_SHIP: 2, KEEP_RUNNING: 3}[self.call]


def _fails(checks: list[Check], *kinds: str) -> list[Check]:
    return [c for c in checks if c.status == FAIL and c.kind in kinds]


def decide(checks: list[Check], ctx: Context) -> Verdict:
    by_id = {c.id: c for c in checks}
    exp = ctx.snap.experiment
    warnings = [f"{c.title}: {c.summary}" for c in checks if c.status == WARN]
    treatment = ctx.treatment or "the variant"

    if exp.status == "completed":
        return Verdict(DONT_SHIP, "This experiment has already ended; there is nothing left to ship.",
                       [f"Ended {exp.ended_at} with decision '{exp.rollout_decision}'."], warnings)
    if exp.status == "created" or exp.started_at is None:
        return Verdict(KEEP_RUNNING, "The experiment hasn't been launched yet.", ["Start it, then review."], warnings)

    invalid = _fails(checks, VALIDITY)
    if invalid:
        others = [c.summary for c in _fails(checks, READINESS, DECISION)]
        return Verdict(
            DONT_SHIP,
            f"Refused. The result can't be trusted, whatever its {_chance(ctx)} chance to win says.",
            [c.summary for c in invalid] + others,
            warnings,
        )

    guardrail = by_id["guardrail"]
    if guardrail.status == FAIL:
        return Verdict(DONT_SHIP, "Refused. The guardrail is credibly worse: keep control.", [guardrail.summary],
                       warnings)

    sample = by_id["sample_size"]
    if sample.status == FAIL:
        if sample.data.get("hard_stop_passed"):
            return Verdict(DONT_SHIP, "Refused. The test ran out of time before it had enough data.",
                           [sample.summary], warnings)
        return Verdict(
            KEEP_RUNNING,
            "Not yet. The pre-registered sample size or runtime isn't reached.",
            [sample.summary,
             f"The current {_chance(ctx)} chance to win is not a decision under the pre-registered rule."],
            warnings,
        )

    rule = by_id["stopping_rule"]
    if rule.status == FAIL:
        return Verdict(DONT_SHIP, f"Don't ship {treatment}: the pre-registered rule says keep control.",
                       [rule.summary], warnings)

    novelty = by_id["novelty"]
    if novelty.status == FAIL:
        call = DONT_SHIP if ctx.pre and ctx.pre.hard_stop and ctx.snap.now > ctx.pre.hard_stop else KEEP_RUNNING
        return Verdict(call, "The win is fading over time; let it run before trusting it.", [novelty.summary],
                       warnings)

    interval = by_id["interval"]
    if interval.status == FAIL:
        return Verdict(DONT_SHIP, f"Don't ship {treatment}: it is credibly worse.", [interval.summary], warnings)

    plan = build_plan(ctx)
    if plan is None:
        return Verdict(DONT_SHIP, f"{treatment} won, but it has no variation id to roll out.",
                       ["The variation needs a key in Flagsmith."], warnings)
    return Verdict(SHIP, f"Ship {treatment}. Every check that could block it passed.", [rule.summary], warnings,
                   winner=ctx.treatment, plan=plan)


def _chance(ctx: Context) -> str:
    inf = ctx.inference(ctx.primary, ctx.treatment)
    return f"{inf.chance_to_win:.1%}" if inf else "reported"


def build_plan(ctx: Context) -> RolloutPlan | None:
    exp, env = ctx.snap.experiment, ctx.snap.environment
    option = exp.option_by_key(ctx.treatment) if ctx.treatment else None
    if option is None:
        return None
    split = ", ".join(f"{k} {v * 100:g}%" for k, v in (ctx.shares or {}).items())
    enrolled = f"{exp.rollout_percentage:g}%" if exp.rollout_percentage is not None else "?"
    return RolloutPlan(
        environment_name=env.name,
        environment_id=env.id,
        environment_key=env.api_key,
        production=env.looks_like_production,
        experiment_id=exp.id,
        experiment_name=exp.name,
        feature_name=exp.feature_name,
        variant_key=option.key or str(option.id),
        variant_option_id=option.id,
        path=f"api/v1/environments/{env.api_key}/experiments/{exp.id}/complete/",
        body={"rollout_decision": "variant", "rollout_variant": option.id},
        before=f"experiment '{exp.name}' {exp.status}; {enrolled} of identities split {split}",
        after=(f"experiment completed; '{exp.feature_name}' serves '{option.key}' to 100% of {env.name} "
               "(environment default), experiment rollout removed"),
    )
