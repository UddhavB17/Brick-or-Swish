import { EVENTS } from './flags';
import type { ExperimentClient } from './client';

const QUIT_WINDOW_MS = 10_000;

/**
 * Turns game lifecycle moments into the experiment's conversion events.
 * All events share the identity passed to `flagsmith.identify()`.
 */
export class Telemetry {
  private shotsThisSession = 0;
  private firstMissAt: number | null = null;
  private engagedSinceFirstMiss = false;
  private quitReported = false;

  constructor(private readonly client: ExperimentClient) {
    // `pagehide` is the reliable unload signal on iOS Safari; `visibilitychange` covers app switching.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') this.endSession('hidden');
    });
    window.addEventListener('pagehide', () => this.endSession('pagehide'));
  }

  roundStarted(round: number): void {
    if (this.firstMissAt !== null) this.engagedSinceFirstMiss = true;
    if (round >= 2) {
      this.client.track(EVENTS.SECOND_ROUND_STARTED, { metadata: { round } });
    }
  }

  shotTaken(): void {
    this.shotsThisSession += 1;
    if (this.firstMissAt !== null) this.engagedSinceFirstMiss = true;
  }

  /** Call after `resolveMissFeedback()` so the exposure precedes every conversion. */
  missShown(): void {
    if (this.firstMissAt === null) this.firstMissAt = performance.now();
  }

  roundCompleted(score: number, round: number): void {
    this.client.track(EVENTS.ROUND_COMPLETED, { value: score, metadata: { round } });
    void this.client.flush('round complete');
  }

  shared(): void {
    if (this.firstMissAt !== null) this.engagedSinceFirstMiss = true;
    this.client.track(EVENTS.SCORE_SHARED);
  }

  private endSession(reason: 'hidden' | 'pagehide'): void {
    if (
      this.firstMissAt !== null &&
      !this.quitReported &&
      !this.engagedSinceFirstMiss &&
      performance.now() - this.firstMissAt <= QUIT_WINDOW_MS
    ) {
      this.quitReported = true;
      this.client.track(EVENTS.QUIT_WITHIN_10S, {
        metadata: { seconds_after_miss: Math.round((performance.now() - this.firstMissAt) / 100) / 10 },
      });
    }
    if (this.shotsThisSession > 0) {
      this.client.track(EVENTS.SHOTS_TAKEN, { value: this.shotsThisSession });
      this.shotsThisSession = 0;
    }
    void this.client.flush(reason);
  }
}
