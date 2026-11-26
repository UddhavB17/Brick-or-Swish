# third-umpire

Reviews a Flagsmith experiment before anyone ships the winner. Reads the experiment through the official Flagsmith
CLI, runs deterministic checks against a pre-registration (`HYPOTHESIS.md`), calls SHIP, DON'T SHIP or KEEP RUNNING,
and ends the experiment with the winner at 100% only after a human approves the exact change.

The project overview, screenshots and the Agent Skill are in the [repo README](../README.md#tracks-02-and-04-third-umpire).

```bash
uv run third-umpire review --fixture bad-peeking     # refused
uv run third-umpire review --fixture healthy         # approve at the prompt
uv run third-umpire review -e <client-side key>      # live, via `flagsmith api`
uv run --extra test pytest                           # tests
```

## Commands

| Command | What it does |
| --- | --- |
| `review` | Review one experiment. `--fixture NAME` or `-e KEY` (`FLAGSMITH_ENVIRONMENT`), `--experiment ID` if more than one is running, `--hypothesis PATH`, `--api-url URL` (`FLAGSMITH_API_URL`). |
| `review --dry-run` | Show the rollout command, send nothing. |
| `review --approve "PHRASE"` | Non-interactive approval with the phrase a human typed (for agents and CI). |
| `review --no-gate` | Review only. |
| `review --json` | One compact JSON line on stdout (for agents); the report goes to stderr. |
| `review --explain auto\|template\|off` | Plain-English summary from an LLM when a key is set, else a template. |
| `review --token-log FILE` | Token count of every CLI response and of the output. |
| `review --svg FILE` | Save the terminal report as an SVG. |
| `list` | Experiments in an environment. |
| `fixtures` | Bundled fixtures. |
| `serve-fixture NAME --port 8765` | Serve a fixture as a local mock of the Flagsmith API, to run the real CLI against it. |
| `count-tokens FILE...` | Count tokens the way `--token-log` does. |

Exit codes: 0 ship (applied, simulated or dry run), 2 don't ship, 3 keep running, 4 ship awaiting approval, 1 error.

## Explanations

| Variable | Meaning |
| --- | --- |
| `UMPIRE_LLM_PROVIDER` | `openai`, `anthropic`, `xai`, or `none`. Unset: the first of these whose own key variable is set. |
| `UMPIRE_LLM_API_KEY` | Key for the provider named above (else its own `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `XAI_API_KEY`). |
| `UMPIRE_LLM_MODEL` | Model id (defaults: `gpt-4.1-mini`, `claude-3-5-haiku-latest`, `grok-3-mini`). |
| `UMPIRE_LLM_BASE_URL` | OpenAI-compatible base URL override. |

The model gets only the computed facts and the verdict. Its answer is rejected (and the template used instead) if it
names a different verdict, contradicts the call, or quotes a percentage that isn't in the facts.

## Layout

| Path | Role |
| --- | --- |
| `third_umpire/flagsmith.py` | `flagsmith api` calls with `--jq` projections; fixture backend; the one write (`complete/`). |
| `third_umpire/model.py` | Parsed experiment, exposures, results, audit entries. |
| `third_umpire/hypothesis.py` | Reads the stopping rule, sample size, split and metrics from HYPOTHESIS.md. |
| `third_umpire/stats.py` | Flagsmith's delta-method lift and interval, chance to win, chi-squared SRM. |
| `third_umpire/checks.py` | The checks. |
| `third_umpire/verdict.py` | Verdict order and the rollout plan. |
| `third_umpire/gate.py` | Human approval, dry run, stale-state guard. |
| `third_umpire/explain.py` | Optional LLM explanation with template fallback. |
| `third_umpire/report.py` | Terminal, markdown and JSON output. |
| `third_umpire/mockserver.py` | Local mock of the Flagsmith API for end-to-end runs of the real CLI. |
| `third_umpire/fixtures/` | `bad-peeking`, `healthy`, `keep-running`, and the HYPOTHESIS.md they're judged against. |
| `tools/build_fixtures.py` | Deterministic simulator that regenerates the fixtures. |
| `tools/terminal_screenshots.py` | Regenerates `docs/screenshots/umpire-*.png`. |
