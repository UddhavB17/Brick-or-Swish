# Pre-registered hypothesis — `miss_feedback`

> **Registered:** 2026-11-26, before the experiment was created or launched in Flagsmith.
> The git history of this file is the pre-registration record. Any change after launch goes in
> [Amendments](#amendments) with a UTC timestamp and a reason; the original text above it stays untouched.

## Hypothesis

**Showing near-miss feedback after a missed shot increases the share of players who start a second round.**

Players who are told *how close* they were ("So close, 0.04s late!") and shown a ghost ball replaying the
perfect release will feel the next shot is winnable, so more of them will press **Play again** after the round.

- **Change:** the miss screen only. Everything else (meter, physics, sounds, slow-mo, results screen, dwell time) is identical in both arms.
- **Expected direction:** increase.
- **Minimum effect we care about:** +10 percentage points absolute on the primary metric.
- **Timeframe:** the hackathon window, 2026-11-26 to 2026-11-29.

## Variants (multivariate flag `miss_feedback`)

| Key | Who | What a player sees on a miss |
| --- | --- | --- |
| `control` | 50% of enrolled identities | Plain stamp: `MISS` (rim-out) or `BRICK` (brick/airball). No timing info. |
| `near_miss` | 50% of enrolled identities | "SO CLOSE!" / "ALMOST!" headline, the exact timing error (e.g. `0.04s LATE`), a timing strip, and a ghost-ball replay of the perfect shot. |

Makes (swish / rim-in) look the same in both arms.

## Exposure

An identity is exposed at the **first miss screen it sees** (`flagsmith.getExperimentFlag('miss_feedback')`, called at the
moment the miss feedback renders). Players who never miss are never enrolled. Flagsmith deduplicates exposures per identity,
and conversions only count after the first exposure.

Identity = a stable anonymous visitor id (`anon_<uuid>`) persisted in `localStorage` and passed to `flagsmith.identify()`
before any flag is read.

## Metrics

| Role | Event | Aggregation | Direction | Definition |
| --- | --- | --- | --- | --- |
| **Primary** | `second_round_started` | Occurrence | Higher is better | Player starts round 2 or later (presses Play again) after exposure. |
| **Guardrail** | `quit_within_10s` | Occurrence | Lower is better | Player leaves (tab hidden, closed or navigated away) within 10 s of their first miss screen without shooting again, starting a round or sharing. |
| Informational | `shots_taken` | Mean | Informational | Shots taken per session (session ends when the page is hidden or closed). Sent with `value` = shot count. |
| Informational (optional) | `round_completed` | Mean | Informational | Round score (0–15), sent with `value`. |
| Informational (optional) | `score_shared` | Occurrence | Informational | Player opened the share flow from the results screen. |

## Sample size

Planning assumptions for the primary metric (two-proportion test, used only to size the test; Flagsmith analyses it with its
Bayesian engine):

- Baseline (control) replay rate after a miss: **35%** (our best guess for a casual web game).
- Minimum detectable effect: **+10 pp** (35% → 45%, about +29% relative).
- α = 0.05 (two-sided), power = 0.80.

n per arm = (1.96 + 0.84)² × (0.35·0.65 + 0.45·0.55) / 0.10² ≈ **373**, rounded up to **375 exposed identities per arm (750 total)**.

Rollout 100% of identities, split 50/50.

## Stopping rule (decided now, not later)

1. **No decision before** both arms have **≥ 375 exposed identities** *and* the experiment has run **≥ 24 hours**.
2. **Ship `near_miss`** if chance to beat control on `second_round_started` is **≥ 95%** *and* the guardrail is not credibly worse
   (the 95% credible interval for `quit_within_10s` lift does not sit entirely above zero).
3. **Keep `control`** if chance to beat control is **≤ 5%**, or if the guardrail is credibly worse, whatever the primary says.
4. Anything else is **inconclusive**: keep `control` and report it as inconclusive.
5. **Hard stop:** 2026-11-29 12:00 IST. If the sample size isn't reached by then, the result is reported as underpowered and
   nothing ships on the strength of it.
6. **Invalid** if Flagsmith shows a sample ratio mismatch warning, or a chi-square test on exposures vs 50/50 gives p < 0.001.
   Fix the cause and re-run as a new experiment.
7. **No mid-test edits** to the flag, its variations, the metrics, the rollout or the split. If something has to change, end the
   experiment, record it under Amendments and start a new one.

We may look at the dashboard while it runs (Flagsmith's Bayesian engine tolerates peeking), but decisions are only taken by
these rules.

## Validation before launch (A/A)

Before launching `miss_feedback`, run an A/A experiment on the multivariate flag **`aa_sanity_check`** (`control` vs `aa_b`,
both render identically) with the same exposure point and metrics. Pass criteria:

- Exposures arrive in both arms with no SRM warning.
- `second_round_started` chance to beat control stays between 5% and 95% (no fake winner).

If the A/A shows a "winner", tracking is broken: stop and debug before running the real test.

## Simulated traffic

`scripts/simulate-traffic.mjs` can generate synthetic sessions for demos and pipeline checks. Simulated identities are prefixed
`sim_`, carry the trait `simulated=true` and send events with `metadata.simulated = true`. **Simulated traffic is never sent to
the environment that runs the real experiment**; use a separate environment (for example `Demo`). No claim about real players
is made from simulated data.

## Amendments

_None yet._
