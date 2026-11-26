# HANDOFF: Brick or Swish

Living handoff doc. Update it at every milestone so any person or model can pick up where the last one stopped.
Last updated: 2026-11-26. Phase 1 (game) is PR #1 from `cursor/brick-or-swish-game-8c4e`. Phase 2 (Third Umpire) is on
`cursor/third-umpire-agent-8c4e`, a separate PR to `main` that stacks on PR #1 (merge #1 first).

## What this is

A mobile-first, one-button neon basketball game (Vite + TypeScript, Canvas 2D, no framework) that runs a real Flagsmith
Experimentation A/B test on the miss screen (Track 01), plus **Third Umpire** (Tracks 02 and 04): a Python agent and an
Agent Skill that review the experiment result through the Flagsmith CLI and roll out the winner only with human
approval. Hackathon: WeMakeDevs × Flagsmith Toggle Wars. Deadline Sun 29 Nov 2026, 8:00 PM IST. Pre-registration:
`HYPOTHESIS.md` (do not edit above "Amendments" once launched; the umpire parses it).

## Architecture

```
main.ts ──► Game (loop, phases, physics) ──hooks──► main.ts ──► Ui (DOM overlay)
   │                                                   │
   └──► ExperimentClient (all SDK calls) ◄── Telemetry (game moments → events)
```

- The game knows nothing about Flagsmith. `main.ts` passes `GameHooks`; on a miss it asks
  `experiments.resolveMissFeedback()` for the variant and tells `Ui.showMiss()` what to render.
- Every SDK call lives in `src/flagsmith/client.ts`, so the experiment logic can be audited in one file (phase 2 relies on this).

| File | Role |
| --- | --- |
| `src/main.ts` | Wiring: hooks, input (pointer, Space/Enter, X for X-ray), share flow, best score (`bos_best`), DEV-only `window.__bos`. Dwell: miss 2.1 s, make 1.15 s, identical in both arms. |
| `src/config.ts` | Env vars + URL switches: `?force=control\|near_miss` (no exposure), `?debug` (X-ray + SDK logs). |
| `src/flagsmith/flags.ts` | Flag, variant and event name constants (the contract with Flagsmith). |
| `src/flagsmith/identity.ts` | Stable `anon_<uuid>` in `localStorage['bos_visitor_id']`. |
| `src/flagsmith/client.ts` | `ExperimentClient`: init (`preventFetch`), identify, exposure via `getExperimentFlag`, `track`, `flush`, keepalive fetch, offline fallback, log for X-ray. |
| `src/flagsmith/telemetry.ts` | Maps game moments to events; quit-within-10s logic; flush on `visibilitychange`/`pagehide`. |
| `src/game/world.ts` | World constants (metres), `Camera` with telephoto perspective + tanh shear near the hoop; `fit()` frames hoop/ball per aspect. |
| `src/game/shot.ts` | Timing windows, `classify(error)`, `planShot(error)` → ballistic segments with contacts and slow-mo; `perfectPlan()` for the ghost. |
| `src/game/net.ts` | Spring-mass net (14×5), reacts to the ball. |
| `src/game/particles.ts` | Pooled screen-space particles (sparks, rings, confetti, puffs, embers, motes). |
| `src/game/renderer.ts` | Cached sky/floor layers, board, rim, net, ball, trail, ghost path, crowd, ring meter, post FX. |
| `src/game/game.ts` | Phases `attract → ready → charging → flight → feedback → over`, meter, release error, slow-mo, zoom, shake, ghost replay, attract auto-shots. |
| `src/audio/sfx.ts` | WebAudio synthesis (no files): ticks, swish, clang, board, crowd, buzzer, ambience; `bos_muted`; haptics. |
| `src/ui/ui.ts` | DOM: HUD, callouts (control vs near_miss), results, share modal, toast, X-ray panel. |
| `src/ui/share.ts` | 1080×1350 PNG score card; Web Share with file → text share → download fallback. |
| `src/ui/rank.ts` | Rank titles by score ratio. |
| `src/styles.css` | Design tokens and all UI styles. |
| `scripts/simulate-traffic.mjs` | SIMULATED traffic via `@flagsmith/nodejs` (Demo env only). |
| `scripts/e2e/check-wiring.mjs` | Chrome + real SDK, Flagsmith endpoints intercepted; asserts the whole event contract. |
| `scripts/e2e/screenshots.mjs` | Regenerates `docs/screenshots/` (mobile 390×844 @3x, desktop 1440×900). |
| `docs/flagsmith-setup.md` | Dashboard + CLI steps (warehouse, flags, metrics, A/A, experiment, verify, end, umpire). |

### Third Umpire (`umpire/`, `skills/third-umpire/`)

```
HYPOTHESIS.md ─┐
Flagsmith ── flagsmith api --jq ──► collect ─► checks (PASS/WARN/FAIL + evidence) ─► verdict ─► report (rich, md, json)
                                                                     │                  └─► explain (LLM or template, facts only)
                                                                     └─ SHIP ─► gate (human y/N or typed phrase) ─► complete/ POST
```

- Code decides, never the LLM. The only write is `POST api/v1/environments/<key>/experiments/<id>/complete/` with
  `{"rollout_decision":"variant","rollout_variant":<option id>}`, after a SHIP verdict and approval, and after re-reading
  the experiment (stale guard).
- No direct HTTP to Flagsmith: `flagsmith api` (CLI v2) covers every endpoint, including the audit log and `complete/`.

| File | Role |
| --- | --- |
| `umpire/third_umpire/flagsmith.py` | `FlagsmithCLI` (`flagsmith api <path> --no-input --jq <projection>`), `FixtureBackend`, `collect()`, `complete()`. jq projections `JQ_*` keep payloads small. |
| `umpire/third_umpire/model.py` | Parsed `Environment`, `Experiment` (split from `experiment_rollout`), `Results`, `Exposures`, `AuditEntry`, `Snapshot`. |
| `umpire/third_umpire/hypothesis.py` | Regex parse of HYPOTHESIS.md: 375/arm, 24 h, 95%/5%, hard stop (IST), SRM α 0.001, split 50/50, primary + guardrail events. |
| `umpire/third_umpire/stats.py` | Flagsmith's maths: delta-method lift, 95% CI (±1.96·SE), chance = Φ(lift/SE), chi-squared SRM. |
| `umpire/third_umpire/checks.py` | 11 checks in 3 kinds (validity, readiness, decision); thresholds are constants at the top. |
| `umpire/third_umpire/verdict.py` | Verdict order (completed, validity FAIL, guardrail, sample size, stopping rule, novelty, interval, else SHIP) and `RolloutPlan`. |
| `umpire/third_umpire/gate.py` | Approval: TTY `y` + environment name for production; non-TTY `--approve "ship <variant> to 100% in <Env>"`; `--dry-run`; stale guard. |
| `umpire/third_umpire/explain.py` | OpenAI / Anthropic / xAI via urllib; output validated against the verdict and the facts' percentages, else template. |
| `umpire/third_umpire/report.py` | Terminal report (≤120 cols, 3 evidence lines per failing check), markdown report, compact JSON for agents. |
| `umpire/third_umpire/mockserver.py` | Local mock of the Flagsmith API serving a fixture (auth `Api-Key mock.third-umpire-demo`), implements `complete/`. |
| `umpire/third_umpire/fixtures/` | `bad-peeking` (99.8% after 9 h, SRM, 37 dual-exposed, 4 audit edits, novelty), `healthy` (30 h, all PASS), `keep-running` (14 h). Generated by `umpire/tools/build_fixtures.py` (seeded). |
| `umpire/tests/` | 114 tests: every check pass/fail, verdict, gate, explainer, CLI, real CLI vs mock, skill limits. |
| `skills/third-umpire/SKILL.md` | agentskills.io skill (sections mirror Flagsmith/flagsmith-mcp's `.agents/skills`). Scripts: `umpire` (launcher), `preflight`, `measure-tokens`. References: CHECKS, FLAGSMITH-API, TOKENS. |

## Design system (keep the UI consistent)

- **Look:** synthwave night court. Deep navy-violet sky, striped sun, skyline with lit windows, magenta perspective grid
  floor, cyan court lines, neon-tube backboard, glowing orange rim. Everything glows; nothing is flat grey.
- **Palette** (`PALETTE` in `renderer.ts`, CSS vars in `styles.css`): ink `#f5f7ff`, cyan `#3dfcff`, magenta `#ff2bd6`,
  orange `#ff7a1a`, gold `#ffd23f`, green `#4dff9a` (success / perfect zone), red `#ff3b5c` (miss), night `#05030f`.
  Cyan = makes/info, magenta = brand/secondary, gold/orange = near-miss feedback, red = miss.
- **Fonts:** Bebas Neue for display and all digits (score, stamps, pill-free numbers); Space Grotesk for body, labels and
  the timing pill (`0.09s late`, tabular numbers). Don't use Orbitron (its slashed zero reads as a "no" sign).
- **Neon text:** white-ish core colour + layered `text-shadow` (6px white, 18px/42px colour, 80px soft). Glass panels:
  dark translucent fill, 1px cyan/magenta stroke, soft outer glow, `backdrop-filter` blur.
- **Motion:** stamps slam in with a spring (`--ease-spring`), UI eases out (`--ease-out`). Near misses get slow-mo
  (0.36×), a 1.32 camera zoom on the hoop, letterbox and cyan tint. Makes get flash, sparks, rings, net snap; streaks ≥2
  add embers. `prefers-reduced-motion` turns off CSS animations, camera shake and most of the slow-mo zoom (1.08).
- **Performance (60 fps bar):** static layers are cached offscreen canvases rebuilt only on resize; DPR capped at 2;
  particle pool capped at 600; no assets except Google Fonts (fallback Impact). Bundle ≈ 39 KB gzip; keep it light.
- **Layout:** mobile portrait first. Framing is solved in `Camera.fit()` (portrait hoop 0.34 / ball 0.84 of height,
  landscape 0.37 / 0.80). The X-ray panel sits under the HUD on portrait, bottom-right on desktop.
- **Experiment hygiene in UI:** only the miss callout differs between arms. Results screen, dwell time and sounds must stay
  identical, or the test measures something else.
- **Umpire terminal report:** badges PASS `green3`, WARN `gold1`, FAIL `red3`; verdict panel bordered in the verdict's
  colour; evidence in grey; plain language, no cricket jargon; at most 120 columns. Screenshots come from
  `umpire/tools/terminal_screenshots.py` (rich SVG → Chrome PNG).

## Flagsmith contract

| Kind | Name | Wiring |
| --- | --- | --- |
| Flag | `miss_feedback` (multivariate, string) | Control `control`, variation key `near_miss`. Read at the first miss with `getExperimentFlag` (records `$flag_exposure`). Assignment locked for the session. `variant` or `value` equal to `near_miss` → near-miss UI (covers a post-experiment rollout too). |
| Flag | `aa_sanity_check` (multivariate, string) | Control `control`, variation key `aa_b`. Exposed at the same moment; renders nothing. |
| Event | `second_round_started` | `Telemetry.roundStarted(round ≥ 2)`, metadata `{round}`. Metric: occurrence, `up`. **Primary** (attach first). |
| Event | `quit_within_10s` | On hide/pagehide ≤10 s after first miss with no shot/round/share since, once per page. Metric: occurrence, `down`, expected `not_increase`. |
| Event | `shots_taken` | On hide/pagehide, `value` = shots since last report. Metric: mean, `informational`, expected `not_decrease`. |
| Event | `round_completed` | Every round end, `value` = score. Optional mean metric. Triggers a flush. |
| Event | `score_shared` | Share flow opened. Optional occurrence metric. |

Rules the code relies on: `init({ preventFetch: true, enableEvents: true, fetch: keepaliveFetch, defaultFlags })` then
`identify()`; exposure only when status is ready **and** `loadingState.source === 'SERVER'`; forced/offline/fallback
never record exposures; event names only from `EVENTS`. API enums (from Flagsmith source): aggregation
`occurrence|count|sum|mean`, direction `up|down|informational`, expected direction
`increase|decrease|not_increase|not_decrease`; end with `POST .../experiments/<id>/complete/` and
`{"rollout_decision": "control"|"variant"|"disable"}`.

## Status

Done:
- [x] Game: meter, timing windows, shot planner, physics-like arcs, net, slow-mo rattles, particles, crowd, SFX, haptics, attract mode.
- [x] UI: title, HUD, control and near-miss miss screens, ghost-ball replay, results, share card (Web Share / WhatsApp / save), X-ray.
- [x] Flagsmith client + telemetry with the real JS SDK 12.6; offline fallback logs and stays playable.
- [x] `HYPOTHESIS.md` (pre-registered), `docs/flagsmith-setup.md`, `.env.example`, `vercel.json`, README, OG image.
- [x] Simulator (Node SDK 9.5), dry-run verified; A/A runs show no bias.
- [x] `npm run test:e2e`: 33 checks pass (exposure, same identity, after exposure, flushes, guardrail, offline).
- [x] Screenshots (`docs/screenshots/`), gameplay GIF, PR #1 open.
- [x] Phase 2: `umpire/` CLI (11 checks, verdict, human gate, dry run, markdown/JSON reports, LLM explainer with template
  fallback), 3 fixtures, mock API, 114 tests, ruff clean.
- [x] Phase 2: `skills/third-umpire` validates (`agentskills validate`); token cost measured (3,210 tokens for the full
  demo run, `references/TOKENS.md`).
- [x] Phase 2: README Track 02/04 section + mermaid, setup guide step 11, terminal screenshots, recording of
  refuse → approve through the real CLI against the mock.

In progress: nothing.

## Next steps (priority order)

1. **Live Flagsmith setup** (needs the owner's login): follow `docs/flagsmith-setup.md` in a `Demo` environment, run
   `npm run simulate -- --flag aa_sanity_check`, refresh results, confirm exposures + conversions appear. Then repeat in
   Production, start the A/A, then the real experiment.
2. **Deploy to Vercel** with `VITE_FLAGSMITH_ENVIRONMENT_KEY` (Production key). Then make `og:image` absolute
   (`https://<domain>/og.jpg`) in `index.html`.
3. **First live umpire run**: `cd umpire && uv run third-umpire review --dry-run -e <key> --token-log tokens.json`.
   Compare the audit-log `log` strings and `related_object_type` values with what `checks._audit_relevant` matches
   (taken from Flagsmith source; see Known issues), and add a live row to `references/TOKENS.md`.
4. **Demo video** for judging: gameplay, both miss screens, X-ray panel, the Flagsmith experiment page, then the umpire
   refusing the bad fixture and approving a result (`docs/screenshots/umpire-*.png`, the PR recording).
5. Optional: run the explainer once with a real key per provider (`UMPIRE_LLM_PROVIDER=openai|anthropic|xai`).

## Known issues

Third Umpire:
- Never run against a live Flagsmith project (no credentials on the VM). Verified with the real Flagsmith CLI v2.0.0
  against `serve-fixture` (same paths, auth header and payload shapes as the API source).
- The audit check matches entries by `related_object_type` (`EXPERIMENT`, `FEATURE`, `FEATURE_STATE`, `EF_VERSION`,
  `METRIC`) and id, plus the flag name in `log`. If live entries differ, adjust `_audit_relevant` and add a test.
- Flagsmith's `srm_p_value` is null when the experiment sets the split (it tests the env-default split); the umpire
  recomputes SRM from `experiment_rollout`. Keep that if Flagsmith changes it.
- LLM calls are unit-tested for request shape and output validation only, not against real providers.
- `skills/third-umpire/scripts/umpire` falls back to `uvx --from git+https://github.com/UddhavB17/Brick-or-Swish#subdirectory=umpire`,
  which only works once `umpire/` is on `main`.
- Headless Chrome may not exit after `--screenshot`; `terminal_screenshots.py` kills it once the file is written.

Game:
- Not yet run against a live Flagsmith project or deployed: this VM has no Flagsmith or Vercel credentials. The wiring is
  verified with the real SDK against intercepted endpoints (`npm run test:e2e`).
- The SDK serialises event `value` as a string (`"9"`); confirm mean metrics aggregate it in the live results.
- `getExperimentFlag` is called again on later misses; the SDK resends `$flag_exposure`, which Flagsmith dedupes per identity.
- `shots_taken` is reported per visible stretch (each tab hide sends the count since the last one), so its mean is per stretch.
- Headless Chrome has no Web Share API, so screenshots show WhatsApp + Save image only; real phones also show Share.
- Share card URL uses `location.origin` (shows `127.0.0.1:<port>` in local screenshots).

## Commands

```bash
npm install
npm run dev              # http://localhost:5173 (control until a key is set)
npm run build            # tsc + vite build → dist/
npm run typecheck
npm run test:e2e         # Flagsmith contract in Chrome (CHROME_PATH to override)
npm run screenshots      # docs/screenshots/ (OUT=<dir> to redirect)
npm run simulate -- --dry-run
FLAGSMITH_ENVIRONMENT_KEY=<demo key> npm run simulate -- --flag miss_feedback --sessions 800
```

Debug: `?debug` or **X** opens the X-ray panel; `?force=near_miss` previews a variant; "New identity" resets the bucket.
Playwright video needs `npx playwright-core install ffmpeg` once.

Third Umpire (needs uv, `curl -LsSf https://astral.sh/uv/install.sh | sh`; Flagsmith CLI `curl -fsSL https://get.flagsmith.com | sh`):

```bash
cd umpire
uv run third-umpire review --fixture bad-peeking    # exit 2
uv run third-umpire review --fixture healthy        # exit 4 without a TTY, prompts with one
uv run --extra test pytest                          # 114 tests
uvx ruff check .                                    # lint (config in pyproject.toml)
uv run python tools/build_fixtures.py               # regenerate fixtures (deterministic)
uv run python tools/terminal_screenshots.py         # docs/screenshots/umpire-*.png (needs Chrome + flagsmith)
uv run third-umpire serve-fixture healthy --port 8765 &   # mock API for the real CLI:
export FLAGSMITH_API_URL=http://127.0.0.1:8765 FLAGSMITH_API_KEY_127_0_0_1_8765=mock.third-umpire-demo
cd .. && uvx --from skills-ref agentskills validate skills/third-umpire
skills/third-umpire/scripts/measure-tokens > skills/third-umpire/references/TOKENS.md
```

## Repo rules

- Commits authored as `UddhavB17 <200227057+UddhavB17@users.noreply.github.com>`; no co-author trailers or bot signatures;
  small conventional commits. Cursor cloud agents run a managed `commit-msg` hook that appends a `Co-authored-by` trailer;
  strip it from unpushed commits with
  `git filter-branch -f --msg-filter "sed '/^Co-authored-by: /d' | git stripspace" origin/<branch>..HEAD`
  (for a new branch, use its base instead of `origin/<branch>`).
- Never let the umpire or an agent write to Flagsmith without a human typing the approval. Keep `--dry-run` working.
- Never commit `.env`, `flagsmith.json` or real keys. Client-side keys only in `VITE_` variables.
- Simulated traffic only in the Demo environment.
