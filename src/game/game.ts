import { sfx, haptic } from '../audio/sfx';
import { Net } from './net';
import { Particles } from './particles';
import { Renderer, type BallView, type MeterView, type SceneView, type TrailPoint } from './renderer';
import { POINTS, WINDOWS, isMake, perfectPlan, planShot, sample, type Outcome, type Segment, type ShotPlan } from './shot';
import { WORLD, v3, type Vec3 } from './world';

export type Phase = 'attract' | 'ready' | 'charging' | 'flight' | 'feedback' | 'over';

export interface ShotRecord {
  index: number;
  outcome: Outcome;
  /** Seconds; negative = early, positive = late. */
  error: number;
  points: number;
}

export interface RoundSummary {
  round: number;
  shots: ShotRecord[];
  score: number;
  maxScore: number;
}

export interface FeedbackPlan {
  ghost: boolean;
  dwell: number;
}

export interface GameHooks {
  onRoundStart(round: number): void;
  onShotReleased(index: number): void;
  onShotResolved(shot: ShotRecord, ctx: { streak: number; score: number }): FeedbackPlan;
  onFeedbackEnd(): void;
  onRoundOver(summary: RoundSummary): void;
  onHint(hint: 'hold' | 'tap-again' | 'none'): void;
}

const FILL_TIMES = [1.0, 0.92, 0.85, 0.78, 0.72];
const EASE = 1.25;
const TAP_THRESHOLD_MS = 110;
const MIN_FEEDBACK = 0.7;
const SLOW_SCALE = 0.36;

type BallMode = 'held' | 'planned' | 'free' | 'gone';

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const rand = (a: number, b: number) => a + Math.random() * (b - a);

export class Game {
  readonly renderer: Renderer;
  readonly net = new Net();
  readonly particles = new Particles();
  phase: Phase = 'attract';
  round = 0;
  shotIndex = 0;
  score = 0;
  streak = 0;
  shots: ShotRecord[] = [];

  private time = 0;
  private last = 0;
  private ballMode: BallMode = 'held';
  private ball: Vec3 = { ...WORLD.ballStart };
  private vel: Vec3 = v3(0, 0, 0);
  private spin = 0;
  private spawn = 1;
  private plan: ShotPlan | null = null;
  private segIndex = 0;
  private segT = 0;
  private simT = 0;
  private freeT = 0;
  private resolved = false;
  private timeScale = 1;
  private trail: TrailPoint[] = [];

  private fill = FILL_TIMES[0];
  private perfect = 0.75;
  private pressAt = 0;
  private tapMode = false;
  private meterFraction = 0;
  private meterAlpha = 0;
  private lastTick = 0;
  private inZone = false;

  private feedbackUntil = 0;
  private feedbackMin = 0;
  private ghost: { plan: ShotPlan; t: number; alpha: number; path: Vec3[] } | null = null;
  private attractTimer = 1.6;

  private zoom = 1;
  private shake = 0;
  private flash = 0;
  private boardGlow = 0;
  private rimShake = 0;
  private hype = 0;

  constructor(
    canvas: HTMLCanvasElement,
    private readonly hooks: GameHooks,
    private readonly shotsPerRound = 5,
  ) {
    this.renderer = new Renderer(canvas);
    this.prepareShot(0);
  }

  start(): void {
    this.last = performance.now();
    requestAnimationFrame(this.frame);
  }

  resize(w: number, h: number): void {
    this.renderer.resize(w, h);
  }

  startRound(): void {
    this.round += 1;
    this.shotIndex = 0;
    this.score = 0;
    this.streak = 0;
    this.shots = [];
    this.ghost = null;
    this.prepareShot(0);
    this.respawn();
    this.phase = 'ready';
    this.hooks.onRoundStart(this.round);
    this.hooks.onHint('hold');
  }

  // ---------------------------------------------------------------- input

  press(at: number): void {
    if (this.phase === 'feedback') {
      if (this.time >= this.feedbackMin) this.advance();
      return;
    }
    if (this.phase === 'ready' && this.spawn >= 1) {
      this.phase = 'charging';
      this.pressAt = at;
      this.tapMode = false;
      this.inZone = false;
      this.meterAlpha = 1;
      this.meterFraction = 0;
      return;
    }
    if (this.phase === 'charging' && this.tapMode) this.release(at);
  }

  lift(at: number): void {
    if (this.phase !== 'charging' || this.tapMode) return;
    if (at - this.pressAt < TAP_THRESHOLD_MS) {
      this.tapMode = true;
      this.hooks.onHint('tap-again');
      return;
    }
    this.release(at);
  }

  // ---------------------------------------------------------------- shot flow

  private prepareShot(index: number): void {
    this.fill = FILL_TIMES[Math.min(index, FILL_TIMES.length - 1)];
    this.perfect = rand(0.62, 0.84);
  }

  private fractionAt(elapsed: number): number {
    return Math.pow(clamp(elapsed / this.fill, 0, 1), EASE);
  }

  private zoneHalf(window: number): number {
    const tPerfect = this.fill * Math.pow(this.perfect, 1 / EASE);
    const slope = (EASE * Math.pow(tPerfect / this.fill, EASE - 1)) / this.fill;
    return window * slope;
  }

  private release(at: number): void {
    const elapsed = (at - this.pressAt) / 1000;
    const tPerfect = this.fill * Math.pow(this.perfect, 1 / EASE);
    const error = Math.min(elapsed, this.fill) - tPerfect;
    this.launch(planShot(error));
    sfx.release();
    haptic(8);
    this.hooks.onShotReleased(this.shotIndex);
    this.hooks.onHint('none');
  }

  private launch(plan: ShotPlan): void {
    this.plan = plan;
    this.segIndex = 0;
    this.segT = 0;
    this.simT = 0;
    this.freeT = 0;
    this.resolved = false;
    this.ballMode = 'planned';
    this.trail = [];
    this.phase = this.phase === 'attract' ? 'attract' : 'flight';
  }

  private resolve(): void {
    if (!this.plan || this.resolved) return;
    this.resolved = true;
    if (this.phase === 'attract') return;
    const outcome = this.plan.outcome;
    const points = POINTS[outcome];
    const made = isMake(outcome);
    this.streak = made ? this.streak + 1 : 0;
    this.score += points;
    const shot: ShotRecord = { index: this.shotIndex, outcome, error: this.plan.error, points };
    this.shots.push(shot);

    if (outcome === 'swish') sfx.crowd(this.streak >= 2 ? 'roar' : 'cheer');
    else if (outcome === 'make') sfx.crowd('cheer');
    else if (outcome === 'rimout') sfx.crowd('ooh');
    else sfx.crowd('aww');
    this.hype = made ? (outcome === 'swish' ? 1 : 0.7) : 0;

    const fb = this.hooks.onShotResolved(shot, { streak: this.streak, score: this.score });
    if (fb.ghost) this.startGhost();
    this.phase = 'feedback';
    this.feedbackMin = this.time + MIN_FEEDBACK;
    this.feedbackUntil = this.time + fb.dwell;
  }

  private advance(): void {
    this.hooks.onFeedbackEnd();
    this.ghost = null;
    if (this.shotIndex + 1 < this.shotsPerRound) {
      this.shotIndex += 1;
      this.prepareShot(this.shotIndex);
      this.respawn();
      this.phase = 'ready';
      return;
    }
    this.phase = 'over';
    this.ballMode = 'gone';
    sfx.buzzer();
    const maxScore = this.shotsPerRound * POINTS.swish;
    if (this.score === maxScore) this.particles.confetti(this.renderer.camera.width, this.renderer.camera.height);
    sfx.fanfare(this.score >= maxScore * 0.6);
    this.hooks.onRoundOver({ round: this.round, shots: [...this.shots], score: this.score, maxScore });
  }

  private respawn(): void {
    this.ballMode = 'held';
    this.ball = { ...WORLD.ballStart };
    this.vel = v3(0, 0, 0);
    this.spawn = 0;
    this.plan = null;
    this.trail = [];
    this.meterAlpha = 0;
  }

  private startGhost(): void {
    const plan = perfectPlan();
    const path: Vec3[] = [];
    for (const seg of plan.segments) {
      for (let i = 0; i <= 24; i++) path.push(sample(seg, (seg.dur * i) / 24).p);
    }
    this.ghost = { plan, t: -0.15, alpha: 0, path };
  }

  // ---------------------------------------------------------------- loop

  private frame = (now: number) => {
    const dt = clamp((now - this.last) / 1000, 0, 1 / 30);
    this.last = now;
    this.update(dt, now);
    this.renderer.draw(this.view());
    requestAnimationFrame(this.frame);
  };

  private update(dt: number, now: number): void {
    this.time += dt;

    if (this.phase === 'attract') {
      this.attractTimer -= dt;
      if (this.attractTimer <= 0 && this.ballMode === 'held' && this.spawn >= 1) {
        this.launch(planShot(rand(-0.05, 0.05)));
        this.attractTimer = 3.4;
      }
      if (this.resolved && this.ballMode !== 'held' && this.freeT > 1.1) this.respawn();
    }

    if (this.phase === 'charging') {
      const elapsed = (now - this.pressAt) / 1000;
      this.meterFraction = this.fractionAt(elapsed);
      if (now - this.lastTick > 75) {
        sfx.tick(this.meterFraction);
        this.lastTick = now;
      }
      const zone = Math.abs(this.meterFraction - this.perfect) <= this.zoneHalf(WINDOWS.swish);
      if (zone && !this.inZone) sfx.zone();
      this.inZone = zone;
      if (elapsed >= this.fill) this.release(this.pressAt + this.fill * 1000);
    } else {
      this.meterAlpha = Math.max(0, this.meterAlpha - dt * 8);
    }

    if (this.phase === 'feedback' && this.time >= this.feedbackUntil) this.advance();

    this.updateBall(dt);
    this.updateGhost(dt);
    this.net.update(dt, this.ballMode === 'planned' || this.ballMode === 'free' ? this.ball : null);
    this.particles.update(dt);

    const slowTarget = this.timeScale < 0.8 ? 1 : 0;
    this.zoom += ((slowTarget ? 1.32 : 1) - this.zoom) * Math.min(1, dt * (slowTarget ? 3 : 2.2));
    this.shake *= Math.exp(-dt * 9);
    this.flash *= Math.exp(-dt * 7);
    this.boardGlow *= Math.exp(-dt * 3);
    this.rimShake *= Math.exp(-dt * 5);
    this.hype *= Math.exp(-dt * 0.9);
  }

  private updateBall(dt: number): void {
    for (const t of this.trail) t.age += dt;
    this.trail = this.trail.filter((t) => t.age < 0.34);

    if (this.ballMode === 'held') {
      this.spawn = Math.min(1, this.spawn + dt * 3.2);
      const pop = 1 - Math.pow(1 - this.spawn, 3);
      const dip = this.phase === 'charging' ? this.meterFraction * 0.09 : 0;
      this.ball = v3(
        WORLD.ballStart.x,
        WORLD.ballStart.y - (1 - pop) * 0.9 + Math.sin(this.time * 2.6) * 0.012 - dip,
        WORLD.ballStart.z,
      );
      this.spin += dt * (this.phase === 'charging' ? 4 + this.meterFraction * 14 : 0.8);
      return;
    }
    if (this.ballMode === 'gone' || !this.plan) return;

    const seg: Segment | undefined = this.plan.segments[this.segIndex];
    const target = this.ballMode === 'planned' && seg ? seg.slow : 1;
    this.timeScale += (target - this.timeScale) * Math.min(1, dt * (target < this.timeScale ? 14 : 5));
    sfx.swell(this.timeScale < 0.8);
    const simDt = dt * this.timeScale;
    this.simT += simDt;
    this.spin += simDt * 11;

    if (this.ballMode === 'planned' && seg) {
      this.segT += simDt;
      while (this.ballMode === 'planned' && this.segT >= this.plan.segments[this.segIndex].dur) {
        const done = this.plan.segments[this.segIndex];
        this.segT -= done.dur;
        this.contact(done);
        this.segIndex += 1;
        if (this.segIndex >= this.plan.segments.length) {
          const endState = sample(done, done.dur);
          this.ball = endState.p;
          this.vel = this.plan.exit ? { ...this.plan.exit } : endState.v;
          this.ballMode = 'free';
          this.freeT = 0;
        }
      }
      if (this.ballMode === 'planned') {
        this.ball = sample(this.plan.segments[this.segIndex], this.segT).p;
      }
    } else if (this.ballMode === 'free') {
      this.freeT += simDt;
      const steps = 3;
      const h = simDt / steps;
      for (let i = 0; i < steps; i++) {
        this.vel.y -= WORLD.gravity * h;
        this.ball.x += this.vel.x * h;
        this.ball.y += this.vel.y * h;
        this.ball.z += this.vel.z * h;
        if (this.ball.y < WORLD.ballR && this.vel.y < 0) {
          this.ball.y = WORLD.ballR;
          const impact = Math.abs(this.vel.y);
          this.vel.y = -this.vel.y * 0.56;
          this.vel.x *= 0.82;
          this.vel.z *= 0.82;
          if (this.phase !== 'attract') sfx.bounce(impact / 7);
        }
        if (this.ball.z > WORLD.boardZ - WORLD.ballR && this.vel.z > 0 && this.ball.y > WORLD.boardBottom) {
          this.vel.z = -this.vel.z * 0.5;
        }
      }
    }

    if (!this.resolved && this.simT >= this.plan.resolveAt) this.resolve();

    this.trail.push({ p: { ...this.ball }, age: 0 });
    if (this.streak >= 2 && this.phase !== 'attract') {
      const s = this.renderer.project(this.ball);
      this.particles.ember(s.x, s.y, s.s);
    }
  }

  private contact(seg: Segment): void {
    if (seg.contact === 'none') return;
    const quiet = this.phase === 'attract';
    const s = this.renderer.project(sample(seg, seg.dur).p);
    switch (seg.contact) {
      case 'rim': {
        if (!quiet) sfx.clang(seg.intensity);
        this.particles.clang(s.x, s.y + WORLD.ballR * s.s * 0.6, s.s, seg.intensity);
        this.net.jiggle(seg.intensity * 0.9);
        this.rimShake = seg.intensity;
        this.shake = Math.max(this.shake, 7 * seg.intensity);
        if (!quiet) haptic(seg.intensity > 0.7 ? 30 : 12);
        break;
      }
      case 'board': {
        if (!quiet) sfx.board(seg.intensity);
        this.boardGlow = 1;
        this.shake = Math.max(this.shake, 5 * seg.intensity);
        this.particles.puff(s.x, s.y, s.s);
        if (!quiet) haptic(20);
        break;
      }
      case 'net': {
        const clean = this.plan?.outcome === 'swish';
        if (!quiet) sfx.swish();
        this.net.snap(clean ? 1 : 0.6);
        const hoop = this.renderer.project(v3(0, WORLD.rimY, WORLD.hoopZ));
        this.particles.swish(hoop.x, hoop.y, hoop.s * (clean ? 1 : 0.7));
        this.flash = clean ? 0.9 : 0.5;
        this.boardGlow = 1;
        if (!quiet) haptic(clean ? [12, 40, 12] : 14);
        break;
      }
    }
  }

  private updateGhost(dt: number): void {
    const g = this.ghost;
    if (!g) return;
    g.t += dt * 0.95;
    const total = g.plan.segments.reduce((t, s) => t + s.dur, 0);
    const fadeOut = g.t > total ? 1 - (g.t - total) / 0.4 : 1;
    g.alpha = clamp(Math.min((g.t + 0.15) / 0.2, fadeOut), 0, 1);
    if (g.t > total + 0.4) {
      g.t = -0.35;
    }
  }

  private ghostView(): { ball: BallView | null; reveal: number } {
    const g = this.ghost;
    if (!g || g.t < 0) return { ball: null, reveal: g ? 1 : 0 };
    let t = g.t;
    for (const seg of g.plan.segments) {
      if (t <= seg.dur) {
        const total = g.plan.segments.reduce((a, s) => a + s.dur, 0);
        return { ball: { p: sample(seg, t).p, spin: g.t * 11, alpha: g.alpha, ghost: true }, reveal: g.t / total };
      }
      t -= seg.dur;
    }
    const last = g.plan.segments[g.plan.segments.length - 1];
    return { ball: { p: sample(last, last.dur).p, spin: 0, alpha: g.alpha, ghost: true }, reveal: 1 };
  }

  private view(): SceneView {
    const ghost = this.ghostView();
    const showBall = this.ballMode !== 'gone';
    const meter: MeterView | null =
      this.meterAlpha > 0.01
        ? {
            fraction: this.meterFraction,
            perfect: this.perfect,
            swishHalf: this.zoneHalf(WINDOWS.swish),
            makeHalf: this.zoneHalf(WINDOWS.make),
            alpha: this.meterAlpha,
          }
        : null;
    const slowmo = clamp((1 - this.timeScale) / (1 - SLOW_SCALE), 0, 1);
    return {
      time: this.time,
      ball: showBall
        ? { p: this.ball, spin: this.spin, alpha: 1, fire: this.streak >= 2 && this.phase !== 'attract' }
        : null,
      ghost: ghost.ball,
      ghostPath: this.ghost?.path ?? [],
      ghostReveal: ghost.reveal,
      trail: this.ballMode === 'planned' || this.ballMode === 'free' ? this.trail : [],
      meter,
      net: this.net,
      particles: this.particles,
      zoom: this.zoom,
      shakeX: (Math.random() - 0.5) * this.shake,
      shakeY: (Math.random() - 0.5) * this.shake,
      slowmo,
      flash: this.flash,
      boardGlow: this.boardGlow,
      rimShake: this.rimShake,
      hype: this.hype,
      idle: this.phase === 'attract' ? 1 : 0,
    };
  }
}
