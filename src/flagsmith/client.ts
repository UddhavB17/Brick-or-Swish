import flagsmith from '@flagsmith/flagsmith';
import type { IFlagsmithFeature } from '@flagsmith/flagsmith/types';
import { config } from '../config';
import {
  AA_SANITY_FLAG,
  CONTROL_VARIANT,
  MISS_FEEDBACK_FLAG,
  NEAR_MISS_VARIANT,
  type EventName,
  type MissFeedbackVariant,
} from './flags';
import { getOrCreateVisitorId } from './identity';

export type ConnectionStatus = 'disabled' | 'connecting' | 'ready' | 'offline';

export interface FeedbackAssignment {
  variant: MissFeedbackVariant;
  /** `flagsmith` = served by a running experiment (exposure recorded). */
  source: 'flagsmith' | 'flag-value' | 'forced' | 'fallback';
  inExperiment: boolean;
  experimentName: string | null;
}

export interface LogEntry {
  at: number;
  kind: 'info' | 'warn' | 'exposure' | 'event' | 'flush';
  message: string;
}

type Listener = () => void;

const isEventsRequest = (url: string) => url.includes('/v1/events');

/**
 * Browsers cancel normal fetches when a page unloads. `keepalive` lets the final
 * event batch (exposure + conversions) finish after `pagehide`.
 */
const keepaliveFetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  return fetch(input, isEventsRequest(url) ? { ...init, keepalive: true } : init);
};

function platformTrait(): string {
  const coarse = window.matchMedia?.('(pointer: coarse)').matches;
  return coarse ? 'mobile' : 'desktop';
}

/**
 * Owns every Flagsmith call in the app. The game never touches the SDK directly,
 * so the experiment logic stays in one auditable place.
 */
export class ExperimentClient {
  readonly visitorId = getOrCreateVisitorId();
  status: ConnectionStatus = config.flagsmithKey ? 'connecting' : 'disabled';
  readonly log: LogEntry[] = [];

  private assignment: FeedbackAssignment | null = null;
  private aaVariant: string | null = null;
  private listeners = new Set<Listener>();
  private ready: Promise<void> | null = null;

  onChange(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get currentAssignment(): FeedbackAssignment | null {
    return this.assignment;
  }

  get aaAssignment(): string | null {
    return this.aaVariant;
  }

  /** Initialise + identify. Never throws: any failure degrades to control. */
  start(): Promise<void> {
    if (this.ready) return this.ready;
    if (!config.flagsmithKey) {
      this.record('warn', 'VITE_FLAGSMITH_ENVIRONMENT_KEY not set: Flagsmith disabled, miss_feedback defaults to control.');
      this.ready = Promise.resolve();
      return this.ready;
    }

    const connect = async () => {
      await flagsmith.init({
        environmentID: config.flagsmithKey,
        api: config.flagsmithApi,
        enableEvents: true,
        ...(config.flagsmithEventsApi ? { eventProcessorConfig: { eventsApiUrl: config.flagsmithEventsApi } } : {}),
        // Wait for identify(): evaluating environment flags first would bucket nobody.
        preventFetch: true,
        defaultFlags: {
          [MISS_FEEDBACK_FLAG]: { enabled: true, value: CONTROL_VARIANT },
          [AA_SANITY_FLAG]: { enabled: true, value: CONTROL_VARIANT },
        },
        fetch: keepaliveFetch,
        enableLogs: config.debug,
        onError: (err) => this.record('warn', `Flagsmith error: ${err?.message ?? err}`),
      });
      await flagsmith.identify(this.visitorId, { platform: platformTrait() });
    };

    // A slow answer that lands before the first miss still counts; the assignment is only locked at that miss.
    const connected = connect()
      .then(() => {
        this.status = 'ready';
        this.record('info', `Identified ${this.visitorId}; flags loaded from Flagsmith.`);
      })
      .catch((err: unknown) => {
        this.status = 'offline';
        const message = err instanceof Error ? err.message : String(err);
        this.record('warn', `Flagsmith unreachable (${message}); miss_feedback defaults to control.`);
      });

    const timeout = new Promise<void>((resolve) =>
      setTimeout(() => {
        if (this.status === 'connecting') {
          this.record('warn', `Flagsmith has not answered after ${config.flagsTimeoutMs} ms; control is used if it is still silent at the first miss.`);
        }
        resolve();
      }, config.flagsTimeoutMs),
    );

    this.ready = Promise.race([connected, timeout]).finally(() => this.emit());
    return this.ready;
  }

  /**
   * Called at the moment a miss screen renders. The first call locks the assignment
   * for the page session, so a late flag response can never flip a player mid-session.
   * `getExperimentFlag` records the `$flag_exposure` event only for enrolled identities.
   */
  resolveMissFeedback(): FeedbackAssignment {
    if (this.assignment) {
      if (this.assignment.source === 'flagsmith') flagsmith.getExperimentFlag(MISS_FEEDBACK_FLAG);
      return this.assignment;
    }

    if (config.forcedVariant) {
      this.assignment = { variant: config.forcedVariant, source: 'forced', inExperiment: false, experimentName: null };
      this.record('info', `miss_feedback forced to "${config.forcedVariant}" via URL/env; no exposure recorded.`);
    } else if (this.status !== 'ready' || !this.serverFlagsLoaded()) {
      this.assignment = { variant: 'control', source: 'fallback', inExperiment: false, experimentName: null };
      this.record('warn', 'Flags unavailable at first miss: showing control, no exposure recorded.');
    } else {
      const flag = flagsmith.getExperimentFlag(MISS_FEEDBACK_FLAG);
      this.assignment = this.toAssignment(flag);
      if (this.assignment.inExperiment) {
        this.record('exposure', `$flag_exposure miss_feedback = ${flag?.variant ?? '?'} (${this.assignment.experimentName ?? 'experiment'})`);
      } else {
        this.record('info', `miss_feedback = ${this.assignment.variant} (not enrolled in a running experiment; no exposure).`);
      }
      this.exposeAa();
    }
    this.emit();
    return this.assignment;
  }

  track(event: EventName, opts: { value?: number; metadata?: Record<string, unknown> } = {}): void {
    const detail = opts.value !== undefined ? ` value=${opts.value}` : '';
    if (this.status !== 'ready') {
      this.record('event', `${event}${detail} (not sent: Flagsmith ${this.status})`);
      return;
    }
    flagsmith.trackEvent(event, { value: opts.value, metadata: opts.metadata });
    this.record('event', `${event}${detail}`);
  }

  async flush(reason: string): Promise<void> {
    if (this.status !== 'ready') return;
    this.record('flush', `flushEvents (${reason})`);
    await flagsmith.flushEvents();
  }

  private exposeAa(): void {
    const aa = flagsmith.getExperimentFlag(AA_SANITY_FLAG);
    if (!aa) return;
    this.aaVariant = aa.variant ?? String(aa.value ?? CONTROL_VARIANT);
    if (aa.experiment?.inExperiment) {
      this.record('exposure', `$flag_exposure aa_sanity_check = ${this.aaVariant} (A/A)`);
    }
  }

  private toAssignment(flag: IFlagsmithFeature | null): FeedbackAssignment {
    const enrolled = !!flag?.enabled && !!flag.experiment?.inExperiment;
    // `variant` carries the experiment bucket; `value` covers a post-experiment rollout of the winner.
    const isNearMiss = !!flag?.enabled && (flag.variant === NEAR_MISS_VARIANT || flag.value === NEAR_MISS_VARIANT);
    return {
      variant: isNearMiss ? 'near_miss' : 'control',
      source: enrolled ? 'flagsmith' : 'flag-value',
      inExperiment: enrolled,
      experimentName: flag?.experiment?.name ?? null,
    };
  }

  private serverFlagsLoaded(): boolean {
    return String(flagsmith.loadingState?.source) === 'SERVER';
  }

  private record(kind: LogEntry['kind'], message: string): void {
    const entry = { at: Date.now(), kind, message };
    this.log.unshift(entry);
    if (this.log.length > 40) this.log.pop();
    const line = `[BrickOrSwish/flagsmith] ${message}`;
    if (kind === 'warn') console.warn(line);
    else console.info(line);
    this.emit();
  }

  private emit(): void {
    this.listeners.forEach((l) => l());
  }
}

export const experiments = new ExperimentClient();
