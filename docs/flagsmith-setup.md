# Flagsmith setup

Everything Brick or Swish needs in Flagsmith, in the order you need it: environments, warehouse, flags, metrics,
the A/A check, then the real experiment. Each step has a dashboard path and the equivalent Flagsmith CLI v2 command.

The names below are the contract with the code ([`src/flagsmith/flags.ts`](../src/flagsmith/flags.ts)). Event names are
case-sensitive and must match exactly.

| Thing | Name | Notes |
| --- | --- | --- |
| Experiment flag | `miss_feedback` | Multivariate, string. Control value `control`, one variation with key **`near_miss`**. |
| A/A flag | `aa_sanity_check` | Multivariate, string. Control value `control`, one variation with key **`aa_b`**. Renders nothing different. |
| Primary metric | `second_round_started` | Occurrence, higher is better. |
| Guardrail | `quit_within_10s` | Occurrence, lower is better. |
| Informational | `shots_taken` | Mean (event `value` = shots in the session). |
| Optional | `round_completed` | Mean (event `value` = round score 0-15). |
| Optional | `score_shared` | Occurrence. |

## 0. Prerequisites

- A Flagsmith Cloud account (Experimentation is in beta; the managed warehouse is Cloud-only).
- Flagsmith CLI v2+:

  ```bash
  curl -fsSL https://get.flagsmith.com | sh        # or: brew install Flagsmith/tap/flagsmith
  # fallback only: npm install -g @flagsmith/cli
  flagsmith --version                               # must report v2 or later
  flagsmith login                                   # opens the browser
  ```

## 1. Project and environments

Use two environments so simulated traffic can never touch the real result:

| Environment | Used by | Traffic |
| --- | --- | --- |
| `Production` | The deployed game (`VITE_FLAGSMITH_ENVIRONMENT_KEY`) | Real players only |
| `Demo` | `npm run simulate` (`FLAGSMITH_ENVIRONMENT_KEY`) | Simulated players only |

Dashboard: create a project "Brick or Swish" (it comes with Development and Production), then add an environment `Demo`.

CLI:

```bash
flagsmith project list
flagsmith init --create-project "Brick or Swish"          # or: flagsmith init --project "Brick or Swish"
flagsmith environment list
flagsmith environment create Demo --description "Simulated traffic only"
```

`flagsmith init` writes `flagsmith.json` in the repo root; it is git-ignored. Every command below takes
`-e <client-side environment key>` to choose the environment, so run the setup once per environment (Production and Demo).
Flags are project-wide, metrics and experiments are per environment.

```bash
ENV=<client-side environment key>   # Environment Settings › Keys, or `flagsmith environment list`
```

## 2. Warehouse (per environment, required first)

Experiments can't be created, and the events API rejects events, until the environment has a warehouse connection.

Dashboard: **Environment Settings › Warehouse › Flagsmith › Enable**, confirm. Optionally click **Send your first event**.
Status goes *Created → Pending Connection → Connected* once the first event lands (this can take a while the first time).

Check from the CLI:

```bash
flagsmith api api/v1/environments/$ENV/warehouse-connections/
```

An empty list means no warehouse yet: enable it in the dashboard before going on.

## 3. Flags

Create each flag with the control value, then add the variation **with a key**. A variation without a key records no
exposures. `control` is reserved for the flag's own value, and `--variants` on `feature create` can't set keys, so add
variations one at a time. Weights stay 0 here: the experiment sets the split.

Dashboard: **Features › Create Feature**: name `miss_feedback`, value `control`, enabled. Add a variation with value
`near_miss` and key `near_miss`. Repeat for `aa_sanity_check` with a variation `aa_b` / key `aa_b`.

CLI:

```bash
flagsmith feature create miss_feedback --value control --enabled \
  --description "Miss screen copy. control = plain MISS/BRICK, near_miss = timing error + ghost replay"
flagsmith feature variant add miss_feedback --value near_miss --key near_miss --weight 0

flagsmith feature create aa_sanity_check --value control --enabled \
  --description "A/A tracking check. Both variations render identically"
flagsmith feature variant add aa_sanity_check --value aa_b --key aa_b --weight 0

flagsmith feature get miss_feedback --json          # note the feature id and the near_miss variant id
flagsmith feature get aa_sanity_check --json        # note the feature id and the aa_b variant id
```

## 4. Metrics (per environment)

Dashboard: **Metrics › Create Metric** (or from the experiment wizard's Measurement step).

| Name | What do you want to measure? | Direction | Event name |
| --- | --- | --- | --- |
| Second round started | Occurrence | Higher is better | `second_round_started` |
| Quit within 10s of first miss | Occurrence | Lower is better | `quit_within_10s` |
| Shots per session | Mean | Informational | `shots_taken` |
| Round score (optional) | Mean | Informational | `round_completed` |
| Score shared (optional) | Occurrence | Informational | `score_shared` |

CLI (API enums: aggregation `occurrence|count|sum|mean`, direction `up|down|informational`):

```bash
metric() {  # name, aggregation, direction, event
  printf '{"name":"%s","aggregation":"%s","direction":"%s","definition":{"version":1,"event":"%s"}}' "$1" "$2" "$3" "$4" |
    flagsmith api api/v1/environments/$ENV/experiment-metrics/ -X POST --input -
}
metric "Second round started"          occurrence up            second_round_started
metric "Quit within 10s of first miss" occurrence down          quit_within_10s
metric "Shots per session"             mean       informational shots_taken
metric "Round score"                   mean       informational round_completed
metric "Score shared"                  occurrence informational score_shared

flagsmith api api/v1/environments/$ENV/experiment-metrics/     # note each metric id
```

## 5. A/A experiment first (`aa_sanity_check`)

This proves exposures and conversions are joined correctly before the real test. Both arms look identical, so any
"winner" means the tracking is broken.

Dashboard: **Experiments › Create experiment**, flag `aa_sanity_check`, hypothesis "A/A: no difference expected",
metrics as in step 6, 100% of identities, 50/50, then launch.

CLI (replace the ids with the ones from steps 3 and 4):

```bash
cat <<'JSON' | flagsmith api api/v1/environments/$ENV/experiments/ -X POST --input -
{
  "feature": <AA_FEATURE_ID>,
  "name": "A/A sanity check",
  "hypothesis": "A/A: control and aa_b render identically, so no metric should move.",
  "metrics": [
    {"metric": <SECOND_ROUND_METRIC_ID>, "expected_direction": "increase"},
    {"metric": <QUIT_METRIC_ID>, "expected_direction": "not_increase"}
  ],
  "experiment_rollout": {
    "enabled": true,
    "rollout_percentage": 100,
    "feature_state_value": {"type": "string", "value": "control"},
    "multivariate_feature_state_values": [{"multivariate_feature_option": <AA_B_VARIANT_ID>, "percentage_allocation": 50}]
  }
}
JSON
flagsmith api api/v1/environments/$ENV/experiments/<AA_EXPERIMENT_ID>/start/ -X POST
```

Pass criteria (from [HYPOTHESIS.md](../HYPOTHESIS.md)): exposures in both arms, no sample-ratio-mismatch warning, and
chance to beat control on `second_round_started` between 5% and 95%. In `Demo` you can get there in minutes with
`npm run simulate -- --flag aa_sanity_check`.

End it before launching the real test:

```bash
echo '{"rollout_decision":"control"}' |
  flagsmith api api/v1/environments/$ENV/experiments/<AA_EXPERIMENT_ID>/complete/ -X POST --input -
```

## 6. The real experiment (`miss_feedback`)

Commit [HYPOTHESIS.md](../HYPOTHESIS.md) before this step; it is the pre-registration. The first metric attached is the
primary metric, so keep `second_round_started` first.

```bash
cat <<'JSON' | flagsmith api api/v1/environments/$ENV/experiments/ -X POST --input -
{
  "feature": <MISS_FEEDBACK_FEATURE_ID>,
  "name": "Near-miss feedback vs plain miss",
  "hypothesis": "Showing near-miss feedback (exact timing error + ghost replay) after a missed shot increases the share of players who start a second round.",
  "metrics": [
    {"metric": <SECOND_ROUND_METRIC_ID>, "expected_direction": "increase"},
    {"metric": <QUIT_METRIC_ID>, "expected_direction": "not_increase"},
    {"metric": <SHOTS_METRIC_ID>, "expected_direction": "not_decrease"}
  ],
  "experiment_rollout": {
    "enabled": true,
    "rollout_percentage": 100,
    "feature_state_value": {"type": "string", "value": "control"},
    "multivariate_feature_state_values": [{"multivariate_feature_option": <NEAR_MISS_VARIANT_ID>, "percentage_allocation": 50}]
  }
}
JSON
flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/start/ -X POST
flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/          # status should be "running"
```

Each variation gets its `percentage_allocation` and control gets the rest (50/50 here). Once started, the flag is locked:
don't edit the flag, variations, metrics or rollout until the experiment ends (rule 7 of the stopping rule).

## 7. Point the game at Flagsmith

```bash
cp .env.example .env
# VITE_FLAGSMITH_ENVIRONMENT_KEY=<Production client-side key>
npm run dev
```

On Vercel: **Project › Settings › Environment Variables**, add `VITE_FLAGSMITH_ENVIRONMENT_KEY` for Production, redeploy.
It is a client-side key, so it is safe in the bundle; server-side keys must never go in a `VITE_` variable.

## 8. Verify the wiring

1. Open the game with `?debug` (or press **X**) to see the X-ray panel: visitor id, connection status, assigned variant,
   exposure and every event as it is sent.
2. Play until the first miss. The panel should log `$flag_exposure miss_feedback = <variant>`.
3. DevTools › Network: `POST https://events.api.flagsmith.com/v1/events` batches arrive on round end and when the tab
   is hidden (sent with `keepalive` so they survive closing the tab).
4. Check an identity's bucket from the CLI:

   ```bash
   flagsmith evaluate miss_feedback --identity anon_<id from the X-ray panel>
   ```

5. Watch **Experiment › Exposures**; refresh exposures or results on demand (results: once every 5 minutes):

   ```bash
   flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/exposures/refresh/ -X POST
   flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/results/refresh/ -X POST
   flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/results/
   ```

The X-ray panel's **New identity** button clears `bos_visitor_id` and reloads, which gives you a fresh bucket for QA.
`?force=near_miss` or `?force=control` previews a variant without recording an exposure.

## 9. Simulated traffic (Demo environment only)

```bash
FLAGSMITH_ENVIRONMENT_KEY=<Demo client-side key> npm run simulate -- --flag aa_sanity_check --sessions 400
FLAGSMITH_ENVIRONMENT_KEY=<Demo client-side key> npm run simulate -- --flag miss_feedback --sessions 800 --lift 0.10
npm run simulate -- --dry-run          # no key needed: local bucketing, nothing is sent
```

Every simulated identity is `sim_<uuid>` with trait `simulated=true`, and every event carries `metadata.simulated=true`.
The script refuses to run with the game's own key (`VITE_FLAGSMITH_ENVIRONMENT_KEY`) unless you pass `--allow-game-env`.
Simulated results are a pipeline demo, not evidence about players.

## 10. Reading results and ending

- A variation shows **Collecting data** until it has 50 identities (and 5 conversions for occurrence metrics).
- Flagsmith's Bayesian engine reports lift, a 95% credible interval and chance to beat control; 95%+ counts as winning.
- A sample-ratio-mismatch warning means the split is off: treat the run as invalid (stopping rule 6).
- Decide only by the stopping rule in [HYPOTHESIS.md](../HYPOTHESIS.md), then end the experiment. Ending freezes the
  results and unlocks the flag:

  ```bash
  # keep control
  echo '{"rollout_decision":"control"}' |
    flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/complete/ -X POST --input -
  # or ship near_miss to everyone
  echo '{"rollout_decision":"variant","rollout_variant":<NEAR_MISS_VARIANT_ID>}' |
    flagsmith api api/v1/environments/$ENV/experiments/<EXPERIMENT_ID>/complete/ -X POST --input -
  ```

  A `variant` decision makes the environment default serve `near_miss` at 100%; the game reads `flag.value` as well as
  `flag.variant`, so it keeps showing near-miss feedback with no code change.

## Gotchas checklist

- [ ] Warehouse enabled in the environment before creating experiments.
- [ ] Every variation has a key (`near_miss`, `aa_b`).
- [ ] The game identifies before reading flags (`preventFetch: true`, then `identify()`); see `src/flagsmith/client.ts`.
- [ ] Exposure happens where the variant is seen (first miss screen), via `getExperimentFlag`.
- [ ] Event names match metrics exactly, including case.
- [ ] Buffered events are flushed on round end, `visibilitychange` (hidden) and `pagehide`.
- [ ] No edits to the flag while the experiment runs.
- [ ] Simulated traffic only in `Demo`.

## Phase 2: Third Umpire (not built yet)

A Python + Flagsmith CLI agent, packaged as an agentskills.io Agent Skill, that audits a running experiment and asks a
human before acting: sample-ratio mismatch, peeking against the stopping rule, guardrail breaches, novelty effects and
any post-launch edits to the flag, metrics or rollout. It reads only what this setup creates: the experiment, its
metrics, exposures and results endpoints, and the audit trail. See `HANDOFF.md` for where it plugs in.
