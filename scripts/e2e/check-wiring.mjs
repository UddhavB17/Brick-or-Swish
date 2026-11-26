#!/usr/bin/env node
/**
 * End-to-end check of the Flagsmith contract, using the real `@flagsmith/flagsmith` SDK in Chrome with
 * Flagsmith's identity and events endpoints intercepted (no account or network needed).
 *
 * It asserts that the game identifies before reading flags, records the exposure at the first miss, sends
 * every conversion on the same identity after that exposure, flushes on round end and on tab hide, fires the
 * quick-quit guardrail, and stays playable on control when Flagsmith is unreachable.
 *
 *   npm run test:e2e          (set CHROME_PATH if Chrome isn't in a standard location)
 */
import { launchChrome, devices, shoot, startGame, startRound, waitPhase, waitShotDone } from './harness.mjs';

const EVENTS_URL = 'https://events.api.flagsmith.com/v1/events';
const game = await startGame({ port: 5199, env: { VITE_FLAGSMITH_ENVIRONMENT_KEY: 'e2e_fake_key' } });
const browser = await launchChrome();
let failures = 0;

function identityResponse(identifier, variant) {
  const flag = (id, name, value, experimentName) => ({
    feature: { id, name },
    enabled: true,
    feature_state_value: value,
    variant: value,
    metadata: { experiment: { id: id * 10, name: experimentName, in_experiment: true } },
  });
  return {
    identifier,
    flags: [flag(1, 'miss_feedback', variant, 'Near-miss feedback'), flag(2, 'aa_sanity_check', 'aa_b', 'A/A')],
    traits: [],
  };
}

async function play(name, { variant, offline = false, quitAfterFirstMiss = false }) {
  const ctx = await browser.newContext(devices.mobile);
  const page = await ctx.newPage();
  const identifies = [];
  const batches = [];
  const warnings = [];
  page.on('console', (m) => m.type() === 'warning' && warnings.push(m.text()));
  page.on('pageerror', (e) => check(name, false, `page error: ${e.message}`));

  await page.route('**/api/v1/identities/**', async (route) => {
    if (offline) return route.abort('connectionrefused');
    const body = route.request().postDataJSON();
    identifies.push({ at: Date.now(), body });
    await route.fulfill({ json: identityResponse(body.identifier, variant) });
  });
  await page.route('**/api/v1/flags/**', (route) => (offline ? route.abort() : route.fulfill({ json: [] })));
  await page.route(`${EVENTS_URL}*`, async (route) => {
    batches.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: {} });
  });

  await page.goto(game.url);
  await page.waitForTimeout(1200);
  await startRound(page, '.play-btn');
  let missText = '';
  for (const error of [0, 0.09, -0.16, 0.01, 0.02]) {
    await shoot(page, error);
    await waitPhase(page, 'feedback');
    if (error === 0.09) {
      await page.waitForTimeout(200);
      missText = (await page.textContent('.callout'))?.replace(/\s+/g, ' ').trim() ?? '';
      if (quitAfterFirstMiss) break;
    }
    await waitShotDone(page);
  }
  if (!quitAfterFirstMiss) {
    await waitPhase(page, 'over');
    await page.waitForTimeout(1200);
    await startRound(page, '.again-btn');
    await shoot(page, 0.2);
    await waitPhase(page, 'feedback');
  }
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(1200);
  const assignment = await page.evaluate(() => window.__bos.experiments.currentAssignment);
  const round = await page.evaluate(() => window.__bos.game.round);
  await ctx.close();
  const events = batches.flatMap((b) => b?.events ?? []);
  return { identifies, events, batches, warnings, assignment, missText, round };
}

function check(scenario, ok, message) {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${scenario}: ${message}`);
  if (!ok) failures += 1;
}

function checkEnrolled(name, variant, r, { expectReplay }) {
  const id = r.identifies[0]?.body.identifier;
  check(name, r.identifies.length === 1 && /^anon_[0-9a-f-]{36}$/.test(id ?? ''), `identified once as ${id}`);
  check(name, r.assignment?.source === 'flagsmith' && r.assignment.variant === variant, `assignment ${JSON.stringify(r.assignment)}`);
  const exposure = r.events.find((e) => e.event === '$flag_exposure' && e.feature_name === 'miss_feedback');
  check(name, exposure?.value === variant && exposure.identifier === id, `exposure recorded for ${variant}`);
  check(name, r.events.some((e) => e.event === '$flag_exposure' && e.feature_name === 'aa_sanity_check'), 'A/A exposure recorded');
  const conversions = r.events.filter((e) => !e.event.startsWith('$'));
  check(name, conversions.length > 0 && conversions.every((e) => e.identifier === id), 'every conversion uses the same identity');
  check(name, conversions.every((e) => e.timestamp >= exposure.timestamp), 'every conversion is after the exposure');
  const names = new Set(conversions.map((e) => e.event));
  const expected = expectReplay ? ['round_completed', 'second_round_started', 'shots_taken'] : ['quit_within_10s', 'shots_taken'];
  check(name, expected.every((n) => names.has(n)), `events sent: ${[...names].join(', ')}`);
  if (expectReplay) check(name, !names.has('quit_within_10s'), 'no quit event for an engaged player');
  check(name, r.batches.length >= (expectReplay ? 2 : 1), `${r.batches.length} event batch(es) flushed`);
}

try {
  console.log('\nFlagsmith wiring (real SDK, intercepted endpoints)\n');

  const near = await play('near_miss', { variant: 'near_miss' });
  checkEnrolled('near_miss', 'near_miss', near, { expectReplay: true });
  check('near_miss', /SO CLOSE!/.test(near.missText) && /0\.09s late/.test(near.missText), `miss screen "${near.missText}"`);

  const control = await play('control', { variant: 'control' });
  checkEnrolled('control', 'control', control, { expectReplay: true });
  check('control', control.missText === 'MISS', `miss screen "${control.missText}"`);

  const quit = await play('quick quit', { variant: 'near_miss', quitAfterFirstMiss: true });
  checkEnrolled('quick quit', 'near_miss', quit, { expectReplay: false });

  const offline = await play('offline', { variant: 'near_miss', offline: true });
  check('offline', offline.assignment?.source === 'fallback' && offline.assignment.variant === 'control', 'falls back to control');
  check('offline', offline.missText === 'MISS', `miss screen "${offline.missText}"`);
  check('offline', offline.round === 2, 'still playable (reached round 2)');
  check('offline', offline.batches.length === 0, 'sends nothing');
  check('offline', offline.warnings.some((w) => w.includes('Flagsmith unreachable')), 'logs that Flagsmith is unreachable');
} finally {
  await browser.close();
  await game.close();
}

console.log(failures ? `\n${failures} check(s) failed\n` : '\nAll wiring checks passed\n');
process.exit(failures ? 1 : 0);
