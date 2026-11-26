// Shared helpers for the browser scripts: a throwaway Vite dev server and a Chrome launcher.
import { existsSync } from 'node:fs';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';

export async function startGame({ port, env = {} }) {
  Object.assign(process.env, env);
  const server = await createServer({ server: { port, strictPort: true, host: '127.0.0.1' }, logLevel: 'error' });
  await server.listen();
  return { url: `http://127.0.0.1:${port}`, close: () => server.close() };
}

export function launchChrome() {
  const executablePath =
    process.env.CHROME_PATH ?? ['/usr/local/bin/google-chrome', '/usr/bin/google-chrome'].find((p) => existsSync(p));
  return chromium.launch({
    ...(executablePath ? { executablePath } : { channel: 'chrome' }),
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
}

export const devices = {
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
};

/** Hold and release so the shot lands `error` seconds from the perfect release (needs the DEV-only `window.__bos`). */
export async function shoot(page, error, { holdOnlyMs = null } = {}) {
  const vp = page.viewportSize();
  await page.mouse.move(vp.width / 2, vp.height * 0.6);
  const delay = await page.evaluate((e) => {
    const g = window.__bos.game;
    return Math.max(10, (g.fill * Math.pow(g.perfect, 1 / 1.25) + e) * 1000);
  }, error);
  await page.mouse.down();
  if (holdOnlyMs !== null) {
    await page.waitForTimeout(holdOnlyMs);
    return delay;
  }
  await page.waitForTimeout(delay);
  await page.mouse.up();
  return delay;
}

export const waitPhase = (page, phase, timeout = 10_000) =>
  page.waitForFunction((p) => window.__bos.game.phase === p, phase, { timeout });

export const waitShotDone = async (page) => {
  await page.waitForFunction(() => ['ready', 'over'].includes(window.__bos.game.phase), null, { timeout: 10_000 });
  await page.waitForTimeout(400);
};

/** Click Play (or Play again) and wait until the game accepts a shot. */
export async function startRound(page, selector) {
  await page.click(selector);
  await waitPhase(page, 'ready');
  await page.waitForTimeout(700);
}
