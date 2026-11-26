import type { MissFeedbackVariant } from './flagsmith/flags';

const params = new URLSearchParams(window.location.search);

function readForcedVariant(): MissFeedbackVariant | null {
  const raw = (params.get('force') ?? import.meta.env.VITE_FORCE_MISS_FEEDBACK ?? '').trim();
  return raw === 'near_miss' || raw === 'control' ? raw : null;
}

export const config = {
  flagsmithKey: (import.meta.env.VITE_FLAGSMITH_ENVIRONMENT_KEY ?? '').trim(),
  flagsmithApi: (import.meta.env.VITE_FLAGSMITH_API ?? '').trim() || undefined,
  flagsmithEventsApi: (import.meta.env.VITE_FLAGSMITH_EVENTS_API ?? '').trim() || undefined,
  /** QA override. A forced variant never records an exposure, so it cannot pollute results. */
  forcedVariant: readForcedVariant(),
  /** `?debug` opens the Flag X-Ray panel on load. */
  debug: params.has('debug'),
  /** Max time to wait for Flagsmith before the game falls back to control. */
  flagsTimeoutMs: 4000,
  shotsPerRound: 5,
} as const;
