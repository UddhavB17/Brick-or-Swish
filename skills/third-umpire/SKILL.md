---
name: third-umpire
description: Reviews a Flagsmith A/B test result before anyone ships the winner, then rolls the winner out only after a human approves the exact change. Deterministic checks (sample ratio mismatch, users in both variants, one-sided exposures, flat conversions, credible interval vs zero, guardrail regression, novelty, the pre-registered stopping rule and sample size, post-launch edits in the audit log) return SHIP, DON'T SHIP or KEEP RUNNING. Use when someone asks whether a Flagsmith experiment is ready to ship or trustworthy, or wants to end one and roll out the winning variation.
compatibility: Requires the Flagsmith CLI v2+, uv (or Python 3.10+ with rich), network access to the Flagsmith API, and a HYPOTHESIS.md pre-registration. Fixture mode needs no account.
metadata:
  author: UddhavB17
  version: "0.1.0"
  source: https://github.com/UddhavB17/Brick-or-Swish
---

# Third Umpire

The umpire reads the experiment through the Flagsmith CLI, runs every check in code and decides. You run it, relay the verdict, and carry the human's approval. Paths below are relative to this skill's directory.

## Rules

- The verdict is the umpire's. Don't overrule it, soften it or re-derive it from the numbers.
- Pass `--approve` only with a phrase the human typed in this conversation, word for word. "Yes", "go ahead" or "ship it" are not approval. The JSON contains the phrase so you can show it, not so you can use it.
- Never write to Flagsmith yourself (no `flagsmith api ... -X POST/PUT/PATCH/DELETE`, no flag or experiment edits). The umpire's gated `complete/` call is the only write this skill makes.
- Never put API keys on the command line. The CLI reads `flagsmith login` or `FLAGSMITH_API_KEY`.
- If you are unsure, use `--dry-run`. It prints the exact request and sends nothing.

## Workflow

1. Preflight: `scripts/preflight`. Fix any `BLOCKER` line before a live review (`note` lines are fine).
2. Review: `scripts/umpire review -e <client-side environment key> --json`. Add `--experiment <id>` if more than one is running (`scripts/umpire list -e <key>` shows them) and `--hypothesis <path>` if HYPOTHESIS.md isn't in or above the working directory. Read stdout only; never fetch the raw experiment data yourself.
3. Act on the exit code:

| Exit | Meaning | What you do |
| --- | --- | --- |
| 2 | DON'T SHIP | Say it was refused, give `headline` and `reasons`. Nothing changed in Flagsmith. Stop. |
| 3 | KEEP RUNNING | Give `headline`, `reasons` and when to look again (from `explanation`). Stop. |
| 4 | SHIP, not applied yet (`approval.outcome` is `awaiting-approval`, `declined` or `stale`) | Show `plan` (environment, flag, before, after, request) and ask the human to type `approval.confirm_phrase`. |
| 0 | SHIP, done (`applied`, `simulated` for fixtures, or `dry-run`) | Report the outcome; `applied` includes `status_after`. |
| 1 | Error | Show stderr. 401: run `flagsmith login`. 404: wrong environment key or experiment id. |

4. Approve: only after the human types the phrase, run the same review again with `--approve "<their phrase>"`. The umpire re-runs every check and re-reads the experiment before it writes. If anything moved, the outcome is `stale` (exit 4): show the new plan and ask again.

A `--json` run prints one line. Trimmed (real output has more fields):

```json
{"verdict":"SHIP","headline":"Ship near_miss. Every check that could block it passed.",
 "experiment":{"id":412,"flag":"miss_feedback","environment":"Production"},
 "claim":"near_miss vs control on second_round_started: +34.2% lift, 99.9% chance to beat control",
 "reasons":["Rule 2: ship near_miss (99.9% chance to beat control, guardrail not credibly worse)."],
 "checks":{"srm":"PASS","dual_exposure":"PASS","audit":"PASS","sample_size":"PASS"},
 "plan":{"environment":"Production","production":true,"flag":"miss_feedback","variant":"near_miss",
         "request":"POST api/v1/environments/<key>/experiments/412/complete/",
         "body":{"rollout_decision":"variant","rollout_variant":77815},"before":"...","after":"..."},
 "approval":{"outcome":"awaiting-approval","confirm_phrase":"ship near_miss to 100% in Production"},
 "explanation":{"source":"template","text":"Ship near_miss. It beats control ..."}}
```

`explanation.text` is a plain-English summary you can relay. It comes from an LLM when `UMPIRE_LLM_PROVIDER` (`openai`, `anthropic`, `xai`) and a key are set, otherwise from a template. Either way it is checked against the verdict and can't change it.

## Without a Flagsmith account

Fixtures replay recorded experiments, and approving one simulates the write:

```bash
scripts/umpire fixtures                                  # list them
scripts/umpire review --fixture bad-peeking --json       # exit 2: refused, 99.8% chance notwithstanding
scripts/umpire review --fixture healthy --json           # exit 4: awaiting approval
scripts/umpire review --fixture healthy --json --approve "ship near_miss to 100% in Production"
```

For a human watching, drop `--json` to get the full umpire's report in the terminal.

## More

- [references/CHECKS.md](references/CHECKS.md): what each check tests, its thresholds, and how the verdict is chosen.
- [references/FLAGSMITH-API.md](references/FLAGSMITH-API.md): the CLI commands, endpoints and `--jq` projections used, auth, and Flagsmith quirks.
- [references/TOKENS.md](references/TOKENS.md): measured token cost of a demo run. `scripts/measure-tokens` re-measures it, and `--token-log FILE` records any run.
