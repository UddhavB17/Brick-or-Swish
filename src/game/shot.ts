import { WORLD, v3, type Vec3 } from './world';

export type Outcome = 'swish' | 'make' | 'rimout' | 'brick' | 'airball';
export type Contact = 'rim' | 'board' | 'net' | 'none';

/** Timing windows in seconds of release error (|actual − perfect|). */
export const WINDOWS = {
  swish: 0.03,
  make: 0.06,
  rimout: 0.11,
  airball: 0.24,
} as const;

export const POINTS: Record<Outcome, number> = { swish: 3, make: 2, rimout: 0, brick: 0, airball: 0 };

export const isMake = (o: Outcome) => o === 'swish' || o === 'make';

export function classify(error: number): Outcome {
  const a = Math.abs(error);
  if (a <= WINDOWS.swish) return 'swish';
  if (a <= WINDOWS.make) return 'make';
  if (a <= WINDOWS.rimout) return 'rimout';
  if (error < -WINDOWS.airball) return 'airball';
  return 'brick';
}

/** One ballistic arc. `slow` is the time scale while it plays (slow-mo on rim rattles). */
export interface Segment {
  p0: Vec3;
  v0: Vec3;
  dur: number;
  slow: number;
  contact: Contact;
  intensity: number;
}

export interface ShotPlan {
  outcome: Outcome;
  error: number;
  segments: Segment[];
  /** Velocity handed to free flight after the last segment; defaults to the arc's end velocity. */
  exit?: Vec3;
  /** Sim seconds from release until the result is shown. */
  resolveAt: number;
}

const g = WORLD.gravity;
const R = WORLD.rimR;
const B = WORLD.ballR;
const H = WORLD.hoopZ;
const Y = WORLD.rimY;
const ON_RIM = Y + 0.1;
const SLOW = 0.36;

const rand = (a: number, b: number) => a + Math.random() * (b - a);

export function arc(from: Vec3, to: Vec3, dur: number, slow = 1, contact: Contact = 'none', intensity = 1): Segment {
  return {
    p0: from,
    v0: v3((to.x - from.x) / dur, (to.y - from.y) / dur + 0.5 * g * dur, (to.z - from.z) / dur),
    dur,
    slow,
    contact,
    intensity,
  };
}

export function sample(seg: Segment, t: number): { p: Vec3; v: Vec3 } {
  return {
    p: v3(seg.p0.x + seg.v0.x * t, seg.p0.y + seg.v0.y * t - 0.5 * g * t * t, seg.p0.z + seg.v0.z * t),
    v: v3(seg.v0.x, seg.v0.y - g * t, seg.v0.z),
  };
}

const end = (seg: Segment) => sample(seg, seg.dur).p;
const total = (segs: Segment[], upTo = segs.length) => segs.slice(0, upTo).reduce((t, s) => t + s.dur, 0);

const front = (x: number) => v3(x, ON_RIM, H - R + 0.03);
const back = (x: number) => v3(x, ON_RIM, H + R - 0.03);
const center = (x: number) => v3(x, Y, H + 0.01);
const below = (x: number) => v3(x * 0.4, Y - 0.52, H + 0.04);

/** The textbook release: what the ghost ball replays. */
export function perfectPlan(): ShotPlan {
  const start = WORLD.ballStart;
  const s1 = arc(start, center(0), 1.04, 1, 'net', 1);
  const s2 = arc(end(s1), below(0), 0.24);
  return { outcome: 'swish', error: 0, segments: [s1, s2], resolveAt: s1.dur + 0.12 };
}

export function planShot(error: number): ShotPlan {
  const outcome = classify(error);
  const start = WORLD.ballStart;
  const x = rand(-0.025, 0.025);
  const T = 1.04 + Math.max(-0.3, Math.min(0.3, error)) * 0.45;
  const side = Math.random() < 0.5 ? -1 : 1;
  const early = error < 0;
  const segs: Segment[] = [];

  switch (outcome) {
    case 'swish': {
      segs.push(arc(start, center(x * 0.5), T, 1, 'net', 1));
      segs.push(arc(end(segs[0]), below(x), 0.24));
      return { outcome, error, segments: segs, resolveAt: segs[0].dur + 0.1 };
    }
    case 'make': {
      if (early) {
        segs.push(arc(start, front(x), T, 1, 'rim', 0.6));
        segs.push(arc(front(x), back(x * 0.5), 0.3, SLOW, 'rim', 0.35));
      } else if (Math.random() < 0.5) {
        segs.push(arc(start, back(x), T, 1, 'rim', 0.6));
        segs.push(arc(back(x), front(x * 0.5), 0.28, SLOW, 'rim', 0.35));
      } else {
        segs.push(arc(start, v3(x, Y + 0.34, WORLD.boardZ - B), T + 0.04, 1, 'board', 0.6));
      }
      const last = end(segs[segs.length - 1]);
      segs.push(arc(last, center(x * 0.3), 0.2, SLOW, 'net', 0.8));
      segs.push(arc(center(x * 0.3), below(x), 0.24, 0.7));
      return { outcome, error, segments: segs, resolveAt: total(segs, segs.length - 1) + 0.08 };
    }
    case 'rimout': {
      if (early) {
        segs.push(arc(start, front(x), T, 1, 'rim', 0.75));
        segs.push(arc(front(x), back(x + side * 0.04), 0.3, SLOW, 'rim', 0.45));
        const rimSide = v3(side * (R - 0.02), ON_RIM, H);
        segs.push(arc(back(x + side * 0.04), rimSide, 0.26, SLOW, 'rim', 0.3));
        segs.push(arc(rimSide, v3(side * (R + 0.34), Y - 0.22, H - 0.12), 0.3, SLOW));
      } else {
        segs.push(arc(start, back(x), T, 1, 'rim', 0.75));
        segs.push(arc(back(x), front(x + side * 0.03), 0.3, SLOW, 'rim', 0.45));
        segs.push(arc(front(x + side * 0.03), v3(x + side * 0.26, Y - 0.2, H - R - 0.36), 0.32, SLOW));
      }
      return { outcome, error, segments: segs, resolveAt: total(segs) + 0.12 };
    }
    case 'airball': {
      segs.push(arc(start, v3(x, Y - 0.5, H - 0.8), T * 0.96));
      return { outcome, error, segments: segs, resolveAt: total(segs) + 0.3 };
    }
    case 'brick': {
      if (early) {
        segs.push(arc(start, v3(x, Y + 0.02, H - R - B + 0.04), T * 0.97, 1, 'rim', 1));
        return {
          outcome,
          error,
          segments: segs,
          exit: v3(x * 2 + rand(-0.5, 0.5), 2.3, -2.6),
          resolveAt: total(segs) + 0.45,
        };
      }
      if (error > 0.22) {
        segs.push(arc(start, v3(x, Y + 0.8, WORLD.boardZ - B), T + 0.08, 1, 'board', 1));
        return { outcome, error, segments: segs, exit: v3(rand(-0.5, 0.5), 0.6, -2.4), resolveAt: total(segs) + 0.4 };
      }
      segs.push(arc(start, v3(x, Y + 0.42, WORLD.boardZ - B), T + 0.05, 1, 'board', 1));
      segs.push(arc(end(segs[0]), back(x * 0.5), 0.2, 1, 'rim', 0.8));
      return { outcome, error, segments: segs, exit: v3(rand(-0.7, 0.7), 2.2, -2.3), resolveAt: total(segs) + 0.45 };
    }
  }
}
