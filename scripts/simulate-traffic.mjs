#!/usr/bin/env node
/**
 * SIMULATED TRAFFIC for Brick or Swish.
 *
 * Generates synthetic players that behave like the browser game: each one plays shots until its first
 * miss, gets the experiment flag for its own identity at that moment (recording the exposure), then
 * sends the same conversion events the game sends. Nothing here is real player data.
 *
 * Every simulated identity is prefixed `sim_`, carries the trait `simulated=true`, and every event has
 * `metadata.simulated = true`. Point it at a separate Flagsmith environment (for example "Demo"), never
 * the one running the real experiment; it refuses to use the game's own key unless --allow-game-env.
 *
 * Usage:
 *   npm run simulate -- [--flag miss_feedback|aa_sanity_check] [--sessions 400] [--lift 0.10]
 *                       [--concurrency 8] [--seed 42] [--dry-run] [--allow-game-env]
 *
 * Env (read from the shell or .env):
 *   FLAGSMITH_ENVIRONMENT_KEY  client-side key of the DEMO environment (required unless --dry-run)
 *   FLAGSMITH_API              optional, defaults to https://edge.api.flagsmith.com/api/v1/
 *   FLAGSMITH_EVENTS_API       optional, self-hosted events URL
 *   SIM_SESSIONS               default for --sessions
 *   SIM_NEAR_MISS_LIFT         default for --lift (absolute lift in the replay probability, 0.10 = +10 pp)
 */
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { Flagsmith } from '@flagsmith/nodejs';

if (existsSync('.env')) process.loadEnvFile('.env');

const FLAGS = { miss_feedback: 'near_miss', aa_sanity_check: 'aa_b' };
const EVENTS = {
  SECOND_ROUND_STARTED: 'second_round_started',
  QUIT_WITHIN_10S: 'quit_within_10s',
  SHOTS_TAKEN: 'shots_taken',
  ROUND_COMPLETED: 'round_completed',
  SCORE_SHARED: 'score_shared',
};
const SHOTS_PER_ROUND = 5;
// Same timing windows as src/game/shot.ts: |error| <= 0.03 s swish, <= 0.06 s make, otherwise a miss.
const SWISH = 0.03;
const MAKE = 0.06;

// Behaviour model (control arm). The treatment arm adds `lift` to the replay probability and takes
// half of it off the quick-quit probability. For the A/A flag both arms use the control model.
const MODEL = {
  replayAfterRound1: 0.35,
  replayLaterRounds: 0.4,
  quitWithin10s: 0.2,
  share: 0.06,
  maxRounds: 6,
};

const { values: args } = parseArgs({
  options: {
    flag: { type: 'string', default: 'miss_feedback' },
    sessions: { type: 'string', default: process.env.SIM_SESSIONS ?? '400' },
    lift: { type: 'string', default: process.env.SIM_NEAR_MISS_LIFT ?? '0.10' },
    concurrency: { type: 'string', default: '8' },
    seed: { type: 'string' },
    'dry-run': { type: 'boolean', default: false },
    'allow-game-env': { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  },
});

if (args.help) {
  console.log('See the header of scripts/simulate-traffic.mjs for usage.');
  process.exit(0);
}

const flagName = args.flag;
if (!(flagName in FLAGS)) fail(`--flag must be one of: ${Object.keys(FLAGS).join(', ')}`);
const treatmentKey = FLAGS[flagName];
const isAA = flagName === 'aa_sanity_check';
const sessions = toNumber(args.sessions, 'sessions');
const lift = isAA ? 0 : toNumber(args.lift, 'lift');
const concurrency = Math.max(1, toNumber(args.concurrency, 'concurrency'));
const key = process.env.FLAGSMITH_ENVIRONMENT_KEY ?? '';
const dryRun = args['dry-run'] || !key;

if (!dryRun && !args['allow-game-env'] && key === process.env.VITE_FLAGSMITH_ENVIRONMENT_KEY) {
  fail(
    'FLAGSMITH_ENVIRONMENT_KEY is the same key the game uses (VITE_FLAGSMITH_ENVIRONMENT_KEY).\n' +
      'Simulated traffic must go to a separate environment. Pass --allow-game-env only if you really mean it.',
  );
}

const random = makeRandom(args.seed ? toNumber(args.seed, 'seed') : Date.now());

const flagsmith = dryRun
  ? null
  : new Flagsmith({
      environmentKey: key,
      ...(process.env.FLAGSMITH_API ? { apiUrl: process.env.FLAGSMITH_API } : {}),
      enableEvents: true,
      ...(process.env.FLAGSMITH_EVENTS_API ? { eventProcessorConfig: { eventsApiUrl: process.env.FLAGSMITH_EVENTS_API } } : {}),
    });

const stats = {};
let unenrolled = 0;
let neverMissed = 0;
let errors = 0;

banner();

let next = 0;
let done = 0;
await Promise.all(
  Array.from({ length: Math.min(concurrency, sessions) }, async () => {
    while (next < sessions) {
      next += 1;
      try {
        await simulatePlayer();
      } catch (err) {
        errors += 1;
        if (errors <= 3) console.error(`  player failed: ${err instanceof Error ? err.message : err}`);
      }
      done += 1;
      if (done % 50 === 0 || done === sessions) process.stdout.write(`  ${done}/${sessions} simulated players\n`);
    }
  }),
);

if (flagsmith) {
  process.stdout.write('  flushing buffered events…\n');
  await flagsmith.close(20_000);
}

report();

async function simulatePlayer() {
  const identifier = `sim_${randomUUID()}`;
  const traits = { simulated: true, platform: random() < 0.7 ? 'mobile' : 'desktop' };
  const metadata = { simulated: true };
  const sd = 0.045 + random() * 0.08;
  const track = (event, extra = {}) =>
    flagsmith?.trackEvent(event, { identifier, value: extra.value, metadata: { ...metadata, ...extra.metadata } });

  let arm = null;
  let shots = 0;
  let round = 1;

  while (round <= MODEL.maxRounds) {
    if (round >= 2) track(EVENTS.SECOND_ROUND_STARTED, { metadata: { round } });
    let score = 0;
    for (let i = 0; i < SHOTS_PER_ROUND; i += 1) {
      const error = gaussian() * sd;
      shots += 1;
      const abs = Math.abs(error);
      if (abs <= MAKE) {
        score += abs <= SWISH ? 3 : 2;
        continue;
      }
      if (arm) continue;

      // First miss screen: this is the exposure point, exactly like the game.
      arm = await assign(identifier, traits);
      if (!arm) return;
      const s = stats[arm.variant] ?? (stats[arm.variant] = blank());
      s.exposed += 1;
      const quitP = Math.max(0, MODEL.quitWithin10s - (arm.treated ? lift / 2 : 0));
      if (random() < quitP) {
        s.quit += 1;
        s.shots += shots;
        track(EVENTS.QUIT_WITHIN_10S, { metadata: { seconds_after_miss: round1(2 + random() * 7) } });
        track(EVENTS.SHOTS_TAKEN, { value: shots });
        return;
      }
    }

    track(EVENTS.ROUND_COMPLETED, { value: score, metadata: { round } });
    if (!arm) {
      // A perfect round means no miss yet; the player keeps going until one happens.
      if (round === MODEL.maxRounds) neverMissed += 1;
      round += 1;
      continue;
    }

    const s = stats[arm.variant];
    if (random() < MODEL.share) {
      s.shared += 1;
      track(EVENTS.SCORE_SHARED);
    }
    const base = round === 1 ? MODEL.replayAfterRound1 : MODEL.replayLaterRounds;
    const replay = Math.min(0.95, base + (arm.treated ? lift : 0));
    if (random() >= replay) break;
    if (round === 1) s.secondRound += 1;
    round += 1;
  }

  if (arm) stats[arm.variant].shots += shots;
  track(EVENTS.SHOTS_TAKEN, { value: shots });
}

async function assign(identifier, traits) {
  if (!flagsmith) {
    const variant = random() < 0.5 ? 'control' : treatmentKey;
    return { variant, treated: variant === treatmentKey };
  }
  const flag = await flagsmith.getExperimentFlag(flagName, identifier, traits);
  if (!flag.enabled || !flag.experiment?.inExperiment) {
    unenrolled += 1;
    return null;
  }
  const variant = flag.variant ?? String(flag.value ?? 'control');
  return { variant, treated: variant === treatmentKey };
}

function blank() {
  return { exposed: 0, secondRound: 0, quit: 0, shots: 0, shared: 0 };
}

function banner() {
  console.log('');
  console.log('  ┌──────────────────────────────────────────────────────────────┐');
  console.log('  │  SIMULATED TRAFFIC: synthetic players, not real user data.  │');
  console.log('  └──────────────────────────────────────────────────────────────┘');
  console.log(`  flag:        ${flagName}${isAA ? ' (A/A: no simulated effect)' : ''}`);
  console.log(`  players:     ${sessions}  (concurrency ${concurrency})`);
  console.log(`  model:       replay ${pct(MODEL.replayAfterRound1)} control, +${(lift * 100).toFixed(1)} pp treatment`);
  console.log(`  mode:        ${dryRun ? 'DRY RUN (local bucketing, nothing sent)' : 'LIVE (sending to Flagsmith)'}`);
  if (!key && !args['dry-run']) console.log('               FLAGSMITH_ENVIRONMENT_KEY not set, so this is a dry run.');
  console.log('');
}

function report() {
  console.log('');
  console.log(`  SIMULATED results by arm (local tally${dryRun ? '' : '; Flagsmith computes the real analysis'}):`);
  const rows = Object.entries(stats).sort(([a], [b]) => (a === 'control' ? -1 : b === 'control' ? 1 : a.localeCompare(b)));
  console.log('  ' + ['arm', 'exposed', 'round 2', 'quit<10s', 'shots/player', 'shared'].map((h, i) => h.padEnd(i ? 13 : 12)).join(''));
  for (const [variant, s] of rows) {
    const cells = [
      variant,
      String(s.exposed),
      pct(s.secondRound / s.exposed),
      pct(s.quit / s.exposed),
      (s.shots / s.exposed).toFixed(1),
      pct(s.shared / s.exposed),
    ];
    console.log('  ' + cells.map((c, i) => c.padEnd(i ? 13 : 12)).join(''));
  }
  if (unenrolled) console.log(`  ${unenrolled} players were not enrolled (experiment not running, or outside the rollout).`);
  if (neverMissed) console.log(`  ${neverMissed} players never missed, so they were never exposed.`);
  if (errors) console.log(`  ${errors} players failed (see the first errors above).`);
  if (!dryRun) {
    console.log('');
    console.log('  Next: wait about a minute, then refresh the results (allowed once every 5 minutes):');
    console.log('    flagsmith api api/v1/environments/<ENV_KEY>/experiments/<ID>/results/refresh/ -X POST');
    console.log('    flagsmith api api/v1/environments/<ENV_KEY>/experiments/<ID>/results/');
  }
  console.log('');
}

function pct(x) {
  return Number.isFinite(x) ? `${(x * 100).toFixed(1)}%` : '-';
}

function round1(x) {
  return Math.round(x * 10) / 10;
}

function toNumber(raw, name) {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) fail(`--${name} must be a non-negative number (got "${raw}")`);
  return n;
}

function fail(message) {
  console.error(`simulate-traffic: ${message}`);
  process.exit(1);
}

/** mulberry32: small seeded PRNG so a run can be reproduced with --seed. */
function makeRandom(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian() {
  const u = 1 - random();
  const v = random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
