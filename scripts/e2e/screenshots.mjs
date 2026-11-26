#!/usr/bin/env node
/**
 * Captures the README/PR screenshots: mobile and desktop, both miss_feedback variants.
 * Variants are previewed with `?force=` (no exposure is recorded).
 *
 *   npm run screenshots [-- mobile-near]      (writes to docs/screenshots/, or OUT=<dir>)
 */
import { mkdirSync } from 'node:fs';
import { devices, launchChrome, shoot, startGame, startRound, waitPhase } from './harness.mjs';

const OUT = process.env.OUT ?? 'docs/screenshots';
const only = process.argv[2];
mkdirSync(OUT, { recursive: true });

const game = await startGame({ port: 5198, env: { VITE_FLAGSMITH_ENVIRONMENT_KEY: '' } });
const browser = await launchChrome();

async function run(name, device, variant) {
  const ctx = await browser.newContext(devices[device]);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log(`[${name}] page error:`, e.message));
  const snap = (label) => page.screenshot({ path: `${OUT}/${name}-${label}.png` });
  const settle = async () => {
    await waitPhase(page, 'ready');
    await page.waitForTimeout(400);
  };

  await page.goto(`${game.url}/?force=${variant}`);
  await page.waitForTimeout(1800);
  await snap('title');
  await startRound(page, '.play-btn');

  const hold = await shoot(page, -0.12, { holdOnlyMs: 0 });
  await page.waitForTimeout(hold);
  await snap('charging');
  await page.waitForTimeout(110);
  await page.mouse.up();
  await settle();

  await shoot(page, 0);
  await page.waitForTimeout(950);
  await snap('flight');
  await waitPhase(page, 'feedback');
  await page.waitForTimeout(200);
  await snap('swish');
  await settle();

  await shoot(page, 0.085);
  await page.waitForTimeout(1500);
  await snap('rattle');
  await waitPhase(page, 'feedback');
  await page.waitForTimeout(900);
  await snap('miss-rimout');
  await settle();

  await shoot(page, -0.16);
  await waitPhase(page, 'feedback');
  await page.waitForTimeout(700);
  await snap('miss-brick');
  await settle();

  await shoot(page, 0.02);
  await waitPhase(page, 'over');
  await page.waitForTimeout(1600);
  await snap('results');
  await page.click('.share-btn');
  await page.waitForTimeout(1500);
  await snap('share');
  await ctx.close();
}

const jobs = [
  ['mobile-near', 'mobile', 'near_miss'],
  ['mobile-control', 'mobile', 'control'],
  ['desktop-near', 'desktop', 'near_miss'],
  ['desktop-control', 'desktop', 'control'],
].filter(([n]) => !only || n.startsWith(only));

try {
  for (const [name, device, variant] of jobs) {
    await run(name, device, variant);
    console.log('captured', name);
  }
} finally {
  await browser.close();
  await game.close();
}
