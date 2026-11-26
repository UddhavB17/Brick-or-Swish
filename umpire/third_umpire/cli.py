"""third-umpire: review a Flagsmith experiment before anyone ships the winner.

Exit codes: 0 ship (applied, simulated, dry run or review only), 2 don't ship,
3 keep running, 4 ship but not approved, 1 error.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import threading
from pathlib import Path
from typing import Any

from rich.console import Console

from . import __version__, checks, explain, gate, hypothesis, report, verdict
from . import flagsmith as fs
from .tokens import Ledger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="third-umpire", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"third-umpire {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="review an experiment; if it should ship, ask before rolling out")
    source = review.add_mutually_exclusive_group()
    source.add_argument("--fixture", help="review a recorded fixture instead of Flagsmith (name or path)")
    source.add_argument("--environment", "-e", help="client-side environment key (env: FLAGSMITH_ENVIRONMENT)")
    review.add_argument("--experiment", type=int, help="experiment id (default: the one running experiment)")
    review.add_argument("--hypothesis", help="pre-registration file (default: nearest HYPOTHESIS.md)")
    review.add_argument("--api-url", default=os.environ.get("FLAGSMITH_API_URL"), help="Flagsmith API base URL")
    review.add_argument("--dry-run", action="store_true", help="show the rollout that would happen; send nothing")
    review.add_argument("--approve", metavar="PHRASE", help="non-interactive approval: the exact phrase a human typed")
    review.add_argument("--no-gate", action="store_true", help="review only; never offer the rollout")
    review.add_argument("--explain", choices=["auto", "template", "off"], default="auto",
                        help="plain-English explanation: LLM if a key is set (auto), template, or none")
    review.add_argument("--report-dir", default="umpire-reports", help="where the markdown report goes")
    review.add_argument("--no-report", action="store_true", help="don't write the markdown report")
    review.add_argument("--json", action="store_true", help="print a compact JSON summary (for agents)")
    review.add_argument("--verbose", "-v", action="store_true", help="show evidence for passing checks too")
    review.add_argument("--token-log", metavar="FILE", help="write a token count of everything read to FILE")

    listing = sub.add_parser("list", help="list experiments in an environment")
    listing.add_argument("--environment", "-e", help="client-side environment key (env: FLAGSMITH_ENVIRONMENT)")
    listing.add_argument("--api-url", default=os.environ.get("FLAGSMITH_API_URL"))

    sub.add_parser("fixtures", help="list the packaged fixtures")

    mock = sub.add_parser("serve-fixture", help="serve a fixture as a local mock of the Flagsmith API")
    mock.add_argument("fixture")
    mock.add_argument("--port", type=int, default=8765)
    return parser


def _env_key(value: str | None) -> str:
    key = value or os.environ.get("FLAGSMITH_ENVIRONMENT")
    if not key:
        raise fs.FlagsmithError("No environment: pass --environment <client-side key> or set FLAGSMITH_ENVIRONMENT.")
    return key


def _pick_experiment(backend: Any, env_key: str) -> int:
    running = [e for e in fs.list_experiments(backend, env_key) if e.get("status") == "running"]
    if len(running) == 1:
        return int(running[0]["id"])
    names = ", ".join(f"{e['id']} ({e['name']})" for e in running) or "none"
    raise fs.FlagsmithError(f"Pass --experiment: {len(running)} running experiments ({names}).")


def _load_pre(path: str | None, fixture: bool) -> tuple[hypothesis.PreRegistration | None, str | None]:
    target = Path(path) if path else (fs.fixture_hypothesis() if fixture else hypothesis.find_default())
    if target is None:
        return None, "HYPOTHESIS.md not found in this directory or any parent; pass --hypothesis"
    try:
        return hypothesis.load(target), None
    except hypothesis.HypothesisError as exc:
        return None, str(exc)


def _command_line(args: argparse.Namespace, env_key: str | None, experiment_id: int) -> str:
    parts = ["third-umpire", "review"]
    if args.fixture:
        parts += ["--fixture", args.fixture]
    else:
        parts += ["--environment", env_key or "", "--experiment", str(experiment_id)]
        if args.api_url:
            parts += ["--api-url", args.api_url]
    if args.hypothesis:
        parts += ["--hypothesis", args.hypothesis]
    return " ".join(shlex.quote(p) for p in parts)


def cmd_review(args: argparse.Namespace) -> int:
    ledger = Ledger() if args.token_log else None
    console = Console(stderr=args.json, record=True, highlight=False)
    if args.fixture:
        backend: Any = fs.FixtureBackend.load(args.fixture, ledger)
        env_key, experiment_id = backend.environment_key, args.experiment or backend.experiment_id
    else:
        backend = fs.FlagsmithCLI(api_url=args.api_url, ledger=ledger)
        env_key = _env_key(args.environment)
        experiment_id = args.experiment or _pick_experiment(backend, env_key)

    pre, pre_error = _load_pre(args.hypothesis, bool(args.fixture))
    snap = fs.collect(backend, env_key, experiment_id)
    ctx = checks.build_context(snap, pre, pre_error)
    results = checks.run_all(ctx)
    call = verdict.decide(results, ctx)
    explanation = explain.explain(ctx, results, call, mode=args.explain, ledger=ledger)

    if not args.json:
        report.render_terminal(console, ctx, results, call, explanation, verbose=args.verbose)
    outcome = None if args.no_gate else gate.run(call, ctx, backend, console, dry_run=args.dry_run,
                                                 approve=args.approve, show=not args.json)

    path = None
    if not args.no_report:
        markdown = report.render_markdown(ctx, results, call, explanation, outcome,
                                          _command_line(args, env_key, experiment_id))
        path = report.write_markdown(args.report_dir, ctx, markdown)
        if not args.json:
            console.print(f"[grey50]Report saved to {path}[/]")

    if args.json:
        text = json.dumps(report.summary_json(ctx, results, call, explanation, outcome, path),
                          separators=(",", ":"), ensure_ascii=False)
        print(text)
    else:
        text = console.export_text()
    if ledger is not None:
        ledger.record("agent-output", "review --json" if args.json else "review (terminal)", text)
        ledger.write(args.token_log)

    code = gate.EXIT.get(outcome["outcome"]) if outcome else None
    return call.exit_code if code is None else code


def cmd_list(args: argparse.Namespace) -> int:
    backend = fs.FlagsmithCLI(api_url=args.api_url)
    for e in fs.list_experiments(backend, _env_key(args.environment)):
        print(f"{e['id']:>6}  {e['status']:<10} {e.get('feature') or '':<20} {e['name']}")
    return 0


def cmd_fixtures(_: argparse.Namespace) -> int:
    for path in sorted(fs.FIXTURE_DIR.glob("*.json")):
        print(f"{path.stem:<14} {json.loads(path.read_text())['title']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .mockserver import DEMO_KEY, scoped_key_var, serve

    data = json.loads(fs.resolve_fixture(args.fixture).read_text())
    server, _ = serve(data, port=args.port, quiet=False)
    host, port = server.server_address[:2]
    print(f"Mock Flagsmith API for fixture '{args.fixture}' on http://{host}:{port}", file=sys.stderr)
    print(f"  export FLAGSMITH_API_URL=http://{host}:{port}", file=sys.stderr)
    print(f"  export {scoped_key_var(host, port)}={DEMO_KEY}", file=sys.stderr)
    print(f"  third-umpire review --environment {data['environment_key']}", file=sys.stderr)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {"review": cmd_review, "list": cmd_list, "fixtures": cmd_fixtures, "serve-fixture": cmd_serve}
    try:
        return handlers[args.command](args)
    except fs.FlagsmithError as exc:
        Console(stderr=True).print(f"[bold red]Error:[/] {exc}")
        if exc.detail:
            Console(stderr=True).print(exc.detail, style="grey50", markup=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
