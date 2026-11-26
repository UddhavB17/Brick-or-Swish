# Checks and verdict

Every check is plain Python in `umpire/third_umpire/checks.py`, returns PASS, WARN or FAIL, and attaches the numbers behind it (shown in the terminal and markdown reports). No model is involved. Thresholds marked *pre-reg* come from HYPOTHESIS.md; the rest are constants at the top of `checks.py`.

## Validity: can the data be trusted at all?

A FAIL here means DON'T SHIP, whatever the chance to win.

| id | Tests | FAIL when | WARN when |
| --- | --- | --- | --- |
| `preregistration` | HYPOTHESIS.md exists, was registered on or before launch, names the same primary metric and split as the experiment | missing, registered after launch, primary metric or split differs | amendments recorded |
| `srm` | Chi-squared test of exposed identities per arm against the configured split. The umpire recomputes it because Flagsmith tests the environment default split, which is 0% per variation when the experiment sets its own, so Flagsmith reports no SRM p-value | p < α (*pre-reg*, 0.001), or Flagsmith's own p < α | p < 0.01, fewer than 100 exposed, or no split to test |
| `one_sided` | Every arm gets exposures, including in the last third of the run | an arm has none, or none in the last third while another arm got ≥ 20 | exposures logged for unknown variants |
| `dual_exposure` | Identities Flagsmith excluded for seeing more than one variant | more than 1% of identities | any at all (≤ 1%) |
| `conversion_wiring` | Conversions keep arriving as exposures grow, for the primary and guardrail metrics | zero conversions with ≥ 100 exposed, or none in the last third when ≥ 10 were expected | under 25% of the expected conversions in the last third |
| `audit` | Audit log entries after launch (2-minute grace) in this environment that touch the flag, its feature states or versions, the experiment, its rollout or its metrics (*pre-reg* rule 7) | any such edit | paused or resumed, or the audit log can't be read (for example a plan without audit logs) |

## Readiness: is it time to decide?

| id | Tests | FAIL when |
| --- | --- | --- |
| `sample_size` | Smallest arm vs the pre-registered minimum per arm, and runtime vs the minimum hours (*pre-reg*: 375 per arm, 24 h) | either is short. Before the hard stop this is peeking (KEEP RUNNING); after it the test is underpowered (DON'T SHIP) |

## Decision: what does the pre-registered rule say?

| id | Tests | FAIL when | WARN when |
| --- | --- | --- | --- |
| `interval` | Flagsmith's 95% credible interval for the primary metric's lift, re-derived from the raw per-variant sums (delta method, as Flagsmith computes it) | the whole interval is on the losing side | the interval still includes zero, Flagsmith's figures don't reproduce from its own sums (> 1 pp), or there's no interval yet |
| `guardrail` | Each guardrail metric (`quit_within_10s`) for the chosen variant | its interval sits entirely on the harmful side | chance it got worse ≥ 80%, no data yet, or a pre-registered guardrail isn't attached |
| `novelty` | Lift in the first half of the run vs the second half, from the exposure and conversion time series | lift was positive early and is zero or negative late | late lift is under half the early lift, or under 30 identities per arm per half |
| `stopping_rule` | Applies HYPOTHESIS.md rules 1 to 5 to the chance to beat control | anything but rule 2 (ship): not ready (1), guardrail worse or chance ≤ 5% (3), inconclusive (4), underpowered at the hard stop (5) | |

The rule ships at a chance to win of 95% or more. Since the interval is two-sided, a chance between 95% and 97.5% ships with the `interval` WARN shown next to the verdict.

## Verdict order

The first match wins (`umpire/third_umpire/verdict.py`):

1. Experiment already completed: DON'T SHIP. Not started: KEEP RUNNING.
2. Any validity FAIL: DON'T SHIP ("Refused. The result can't be trusted").
3. Guardrail FAIL: DON'T SHIP.
4. `sample_size` FAIL: KEEP RUNNING, or DON'T SHIP once the hard stop has passed.
5. `stopping_rule` FAIL: DON'T SHIP (keep control).
6. `novelty` FAIL: KEEP RUNNING, or DON'T SHIP after the hard stop.
7. `interval` FAIL: DON'T SHIP.
8. Otherwise SHIP, with a rollout plan for the human to approve.

Exit codes: 0 ship (applied, simulated, dry run or `--no-gate`), 2 don't ship, 3 keep running, 4 ship not yet approved, 1 error.
