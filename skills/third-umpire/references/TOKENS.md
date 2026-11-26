# Token cost of a demo run

Measured by `scripts/measure-tokens` on 2026-11-26, counted with tiktoken o200k_base. Re-run it after changing SKILL.md or the review output.

## What lands in the agent's context

| Step | What the agent reads | Tokens |
| --- | --- | ---: |
| Startup, always loaded | `name` and `description` | 213 |
| Activation | SKILL.md body | 1,307 |
| Preflight | `scripts/preflight` | 123 |
| Refuse the bad result (exit 2) | `scripts/umpire review --fixture bad-peeking --json` | 543 |
| Review the healthy result (exit 4) | `scripts/umpire review --fixture healthy --json` | 524 |
| Approve with the human's phrase (exit 0) | `scripts/umpire review --fixture healthy --json --approve "ship near_miss to 100% in Production"` | 500 |
| **Total** | | **3,210** |

## What it never reads

The umpire process reads Flagsmith itself and hands the agent a summary. For one review of the healthy fixture:

| Payload | Tokens |
| --- | ---: |
| Raw API responses as stored in the fixture (environment, metrics, experiment, exposures, results, audit log) | 7,975 |
| The same responses after the `--jq` projections, through the real Flagsmith CLI | 5,730 |
| The JSON summary the agent reads instead | 488 |

No LLM was called (`UMPIRE_LLM_PROVIDER=none`). With a provider configured, `--token-log` also records the prompt and completion tokens the provider reports.

Record a live run the same way:

```bash
scripts/umpire review -e "$FLAGSMITH_ENVIRONMENT" --json --token-log tokens.json
```
