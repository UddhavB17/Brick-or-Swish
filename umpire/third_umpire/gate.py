"""The human approval gate between a SHIP verdict and the one write the umpire makes.

Nothing is written unless the verdict is SHIP and a person approves the exact
change shown. In a terminal that means typing ``y`` (and, for a production
environment, its name). Without a terminal, for example when an agent runs the
umpire, the caller must pass the confirmation phrase the gate printed, which
the agent is instructed to get from the human verbatim.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from typing import Any

from rich.console import Console

from . import flagsmith as fs
from .checks import Context
from .report import render_plan
from .verdict import SHIP, RolloutPlan, Verdict

REFUSED = "refused"
DRY_RUN = "dry-run"
AWAITING = "awaiting-approval"
DECLINED = "declined"
APPLIED = "applied"
SIMULATED = "simulated"
STALE = "stale"

EXIT = {REFUSED: None, DRY_RUN: 0, SIMULATED: 0, APPLIED: 0, AWAITING: 4, DECLINED: 4, STALE: 4}


def cli_command(backend: Any, plan: RolloutPlan) -> str:
    body = json.dumps(plan.body, separators=(",", ":"))
    parts = ["flagsmith", "api", plan.path, "-X", "POST", "--input", "-"]
    api_url = getattr(backend, "api_url", None)
    if api_url:
        parts += ["--api-url", api_url]
    return f"echo {shlex.quote(body)} | " + " ".join(shlex.quote(p) for p in parts)


def _still_reviewable(backend: Any, ctx: Context) -> str | None:
    """Re-read the experiment right before writing; the state approved must be the state reviewed."""
    exp = ctx.snap.experiment
    fresh = fs.fetch_experiment(backend, ctx.snap.environment.api_key, exp.id)
    if fresh.status not in ("running", "paused"):
        return f"experiment is now '{fresh.status}'"
    if fresh.allocations != exp.allocations or fresh.rollout_percentage != exp.rollout_percentage:
        return "the rollout or split changed since the review"
    if [o.id for o in fresh.options] != [o.id for o in exp.options]:
        return "the flag's variations changed since the review"
    return None


def run(
    verdict: Verdict,
    ctx: Context,
    backend: Any,
    console: Console,
    *,
    dry_run: bool = False,
    approve: str | None = None,
    interactive: bool | None = None,
    ask: Callable[[str], str] | None = None,
    show: bool = True,
) -> dict[str, Any]:
    if verdict.call != SHIP or verdict.plan is None:
        return {"outcome": REFUSED, "detail": "Nothing to approve. No change was made in Flagsmith."}
    plan = verdict.plan
    command = cli_command(backend, plan)
    if show:
        render_plan(console, verdict, command)
    info: dict[str, Any] = {"environment": plan.environment_name, "change": f"POST {plan.path}",
                            "body": plan.body}

    if dry_run:
        console.print("[bold]Dry run:[/] nothing was sent to Flagsmith.")
        return {"outcome": DRY_RUN, **info}

    interactive = sys.stdin.isatty() if interactive is None else interactive
    ask = ask or input
    if approve is not None:
        if approve.strip().lower() != plan.confirm_phrase.lower():
            console.print(f"[bold red]Approval phrase doesn't match.[/] Expected: [bold]{plan.confirm_phrase}[/]")
            return {"outcome": DECLINED, "detail": "approval phrase mismatch", **info}
        approved_by = "confirmation phrase"
    elif not interactive:
        console.print("[bold gold1]Approval required.[/] No terminal to ask in. Have a human type this phrase, "
                      f"then re-run with --approve:\n  [bold]{plan.confirm_phrase}[/]")
        return {"outcome": AWAITING, "confirm_phrase": plan.confirm_phrase, **info}
    else:
        answer = ask(f"Apply this change to {plan.environment_name}? Type y to approve [y/N]: ")
        if answer.strip().lower() not in ("y", "yes"):
            console.print("Declined. Nothing was sent to Flagsmith.")
            return {"outcome": DECLINED, **info}
        if plan.production:
            typed = ask(f"{plan.environment_name} is a production environment. Type its name to confirm: ")
            if typed.strip() != plan.environment_name:
                console.print("Name didn't match. Nothing was sent to Flagsmith.")
                return {"outcome": DECLINED, "detail": "production name mismatch", **info}
        approved_by = "terminal prompt"

    if backend.writes_are_simulated:
        fs.complete(backend, plan.environment_key, plan.experiment_id, plan.body)
        console.print(f"[bold]Approved[/] ({approved_by}). Fixture mode: nothing was sent; a live run would execute "
                      "the command above.")
        return {"outcome": SIMULATED, "approved_by": approved_by, **info}

    stale = _still_reviewable(backend, ctx)
    if stale:
        console.print(f"[bold red]Not applied:[/] {stale}. Review again.")
        return {"outcome": STALE, "detail": stale, **info}
    response = fs.complete(backend, plan.environment_key, plan.experiment_id, plan.body)
    fresh = fs.fetch_experiment(backend, plan.environment_key, plan.experiment_id)
    console.print(
        f"[bold green3]Applied[/] ({approved_by}). Experiment {fresh.id} is [bold]{fresh.status}[/], "
        f"rollout decision [bold]{fresh.rollout_decision}[/], variation {fresh.rollout_variant} "
        f"('{plan.variant_key}') now serves 100% of {plan.environment_name}."
    )
    return {"outcome": APPLIED, "approved_by": approved_by, "response": response,
            "status_after": fresh.status, **info}
