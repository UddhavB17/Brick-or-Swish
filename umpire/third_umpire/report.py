"""The umpire's report: a terminal view for people, a markdown file for the record,
and a compact JSON summary for agents."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .checks import DECISION, FAIL, PASS, READINESS, VALIDITY, WARN, Check, Context, pct, when
from .explain import Explanation
from .verdict import DONT_SHIP, KEEP_RUNNING, SHIP, Verdict

BADGE = {PASS: "bold black on green3", WARN: "bold black on gold1", FAIL: "bold white on red3"}
CALL_STYLE = {SHIP: "green3", DONT_SHIP: "red3", KEEP_RUNNING: "gold1"}
GROUPS = [
    (VALIDITY, "VALIDITY", "can the data be trusted?"),
    (READINESS, "READINESS", "is it time to decide?"),
    (DECISION, "DECISION", "what does the pre-registered rule say?"),
]


def first_sentence(text: str) -> str:
    head = text.split(". ", 1)[0]
    return head if head.endswith((".", ")")) else head + "."


def claim(ctx: Context) -> str:
    inf = ctx.inference(ctx.primary, ctx.treatment)
    metric = ctx.primary.event or ctx.primary.name if ctx.primary else "the primary metric"
    if inf is None:
        return f"{ctx.treatment or 'The variant'} vs control on {metric}: no result yet"
    return (f"{ctx.treatment} vs control on {metric}: {pct(inf.lift, True)} lift, "
            f"{pct(inf.chance_to_win)} chance to beat control")


def render_terminal(console: Console, ctx: Context, checks: list[Check], verdict: Verdict,
                    explanation: Explanation | None, verbose: bool = False) -> None:
    snap, exp = ctx.snap, ctx.snap.experiment
    head = Text()
    head.append(exp.name or f"Experiment {exp.id}", style="bold")
    head.append(f"   flag {exp.feature_name}   environment {snap.environment.name}\n", style="grey70")
    head.append(f"experiment {exp.id} · {exp.status} since {when(exp.started_at)} · results as of "
                f"{when(snap.data_time)} · via {snap.source}", style="grey50")
    console.print(Panel(head, title="[bold]THIRD UMPIRE · ON REVIEW[/]", title_align="left",
                        border_style="grey50", padding=(0, 1)))
    console.print(Text.assemble(("  The claim  ", "bold grey70"), (claim(ctx), "bold")))
    console.print()

    for kind, label, question in GROUPS:
        group = [c for c in checks if c.kind == kind]
        if not group:
            continue
        console.print(Text.assemble((f"  {label}", "bold"), (f"  {question}", "grey50")))
        table = Table.grid(padding=(0, 1))
        table.add_column(width=6, no_wrap=True)
        table.add_column(width=27, no_wrap=True)
        table.add_column(ratio=1)
        for c in group:
            table.add_row(Text(f" {c.status} ", style=BADGE[c.status]), Text(c.title, style="bold"),
                          Text(c.summary, style="default" if c.status != PASS else "grey70"))
            if c.status != PASS or verbose:
                for line in c.evidence:
                    table.add_row("", "", Text(f"· {line}", style="grey50"))
        console.print(Padding(table, (0, 0, 1, 2)))

    style = CALL_STYLE[verdict.call]
    body = [Text(verdict.call, style=f"bold {style}"), Text(verdict.headline, style="bold")]
    for i, reason in enumerate(verdict.reasons, 1):
        body.append(Text(f"{i}. {first_sentence(reason)}"))
    if verdict.warnings and verdict.call == SHIP:
        body.append(Text("Warnings to accept before approving:", style="bold gold1"))
        body.extend(Text(f"- {w}", style="gold1") for w in verdict.warnings)
    console.print(Panel(Group(*body), title="[bold]VERDICT[/]", title_align="left", border_style=style,
                        padding=(0, 1)))
    if explanation:
        console.print(Text.assemble(("  In plain English ", "bold"), (f"({explanation.source})", "grey50")))
        console.print(Padding(Text(explanation.text), (0, 2, 1, 2)))


def render_plan(console: Console, verdict: Verdict, command: str) -> None:
    plan = verdict.plan
    assert plan is not None
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold grey70", no_wrap=True)
    grid.add_column()
    env = Text(f"{plan.environment_name} (id {plan.environment_id})")
    if plan.production:
        env.append("  PRODUCTION", style="bold white on red3")
    grid.add_row("Change", Text(f"End experiment {plan.experiment_id} and serve {plan.variant_key} to 100%",
                                style="bold"))
    grid.add_row("Flag", plan.feature_name)
    grid.add_row("Environment", env)
    grid.add_row("Before", plan.before)
    grid.add_row("After", plan.after)
    grid.add_row("Command", Text(command, style="cyan"))
    console.print(Panel(grid, title="[bold]HUMAN APPROVAL REQUIRED[/]", title_align="left",
                        border_style="gold1", padding=(0, 1)))


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(ctx: Context, checks: list[Check], verdict: Verdict, explanation: Explanation | None,
                    gate: dict[str, Any] | None, command_line: str) -> str:
    snap, exp, pre = ctx.snap, ctx.snap.experiment, ctx.pre
    lines = [
        f"# Third Umpire report: {exp.name}",
        "",
        f"**Verdict: {verdict.call}.** {verdict.headline}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Experiment | `{exp.id}` {exp.name} ({exp.status}) |",
        f"| Flag | `{exp.feature_name}` |",
        f"| Environment | {snap.environment.name} (id {snap.environment.id}) |",
        f"| Started | {when(exp.started_at)} |",
        f"| Results as of | {when(snap.data_time)} |",
        f"| Reviewed at | {when(snap.now)} |",
        f"| Source | {snap.source} |",
        f"| Pre-registration | `{pre.path}` sha256 `{pre.sha256[:12]}` |" if pre else "| Pre-registration | missing |",
        f"| Claim | {claim(ctx)} |",
        "",
        "## Reasons",
        "",
    ]
    lines += [f"{i}. {r}" for i, r in enumerate(verdict.reasons, 1)]
    if verdict.warnings:
        lines += ["", "**Warnings:**", ""] + [f"- {w}" for w in verdict.warnings]
    if explanation:
        lines += ["", "## In plain English", "", f"_{explanation.source}_", "", explanation.text]
    lines += ["", "## Checks", "", "| Status | Check | Kind | Finding |", "| --- | --- | --- | --- |"]
    lines += [f"| {c.status} | {c.title} | {c.kind} | {_md_escape(c.summary)} |" for c in checks]
    lines += ["", "## Evidence", ""]
    for c in checks:
        lines += [f"### {c.status} · {c.title}", ""] + [f"- {_md_escape(e)}" for e in c.evidence] + [""]
    if verdict.plan:
        p = verdict.plan
        lines += ["## Rollout plan", "", f"- Environment: **{p.environment_name}** (id {p.environment_id})",
                  f"- Flag: `{p.feature_name}`", f"- Before: {p.before}", f"- After: {p.after}",
                  f"- Request: `POST {p.path}` with `{json.dumps(p.body)}`", ""]
    if gate:
        lines += ["## Approval", "", f"- Outcome: **{gate['outcome']}**"]
        lines += [f"- {k}: {v}" for k, v in gate.items() if k != "outcome"]
        lines += [""]
    lines += ["## Reproduce", "", "```bash", command_line, "```", ""]
    return "\n".join(lines)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "experiment"


def write_markdown(directory: str | Path, ctx: Context, content: str) -> Path:
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = ctx.snap.now.strftime("%Y%m%dT%H%MZ")
    path = folder / f"{ctx.snap.experiment.id}-{slug(ctx.snap.experiment.name)}-{stamp}.md"
    path.write_text(content, encoding="utf-8")
    return path


def summary_json(ctx: Context, checks: list[Check], verdict: Verdict, explanation: Explanation | None,
                 gate: dict[str, Any] | None, report_path: Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "verdict": verdict.call,
        "headline": verdict.headline,
        "experiment": {"id": ctx.snap.experiment.id, "name": ctx.snap.experiment.name,
                       "flag": ctx.snap.experiment.feature_name, "environment": ctx.snap.environment.name},
        "claim": claim(ctx),
        "reasons": verdict.reasons,
        "checks": {c.id: c.status for c in checks},
    }
    if verdict.warnings:
        out["warnings"] = verdict.warnings
    if verdict.plan:
        out["plan"] = verdict.plan.as_dict()
    if gate:
        out["approval"] = {k: v for k, v in gate.items() if k not in ("environment", "change", "body")}
    if explanation:
        out["explanation"] = {"source": explanation.source, "text": explanation.text}
    if report_path:
        out["report"] = str(report_path)
    return out
