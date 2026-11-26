/** Multivariate experiment flag. The flag's own value is the `control` variant. */
export const MISS_FEEDBACK_FLAG = 'miss_feedback';
export const NEAR_MISS_VARIANT = 'near_miss';

/** A/A sanity-check flag: both variants render identically; used to validate tracking before the real test. */
export const AA_SANITY_FLAG = 'aa_sanity_check';
export const AA_VARIANT_B = 'aa_b';

/** Reserved key Flagsmith uses for the control bucket. */
export const CONTROL_VARIANT = 'control';

/** Event names are case-sensitive and must exactly match the metric definitions in Flagsmith. */
export const EVENTS = {
  /** Primary — occurrence, higher is better. */
  SECOND_ROUND_STARTED: 'second_round_started',
  /** Guardrail — occurrence, lower is better. */
  QUIT_WITHIN_10S: 'quit_within_10s',
  /** Informational — mean of `value` (shots per session). */
  SHOTS_TAKEN: 'shots_taken',
  /** Informational — mean of `value` (round score 0–15). */
  ROUND_COMPLETED: 'round_completed',
  /** Informational — occurrence. */
  SCORE_SHARED: 'score_shared',
} as const;

export type EventName = (typeof EVENTS)[keyof typeof EVENTS];

export type MissFeedbackVariant = 'control' | 'near_miss';
