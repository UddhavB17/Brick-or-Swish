import { Camera, WORLD, v3, type Vec3 } from './world';
import { Net } from './net';
import type { Particles } from './particles';

export const PALETTE = {
  ink: '#f5f7ff',
  cyan: '#3dfcff',
  magenta: '#ff2bd6',
  orange: '#ff7a1a',
  gold: '#ffd23f',
  green: '#4dff9a',
  red: '#ff3b5c',
  night: '#05030f',
} as const;

export interface BallView {
  p: Vec3;
  spin: number;
  alpha: number;
  ghost?: boolean;
  fire?: boolean;
}

export interface MeterView {
  fraction: number;
  perfect: number;
  swishHalf: number;
  makeHalf: number;
  alpha: number;
}

export interface TrailPoint {
  p: Vec3;
  age: number;
}

export interface SceneView {
  time: number;
  ball: BallView | null;
  ghost: BallView | null;
  ghostPath: Vec3[];
  ghostReveal: number;
  trail: TrailPoint[];
  meter: MeterView | null;
  net: Net;
  particles: Particles;
  zoom: number;
  shakeX: number;
  shakeY: number;
  slowmo: number;
  flash: number;
  boardGlow: number;
  rimShake: number;
  hype: number;
  idle: number;
}

interface Person {
  x: number;
  h: number;
  w: number;
  phase: number;
  phone: boolean;
  tint: number;
}

interface Mote {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  a: number;
}

const TAU = Math.PI * 2;
const rand = (a: number, b: number) => a + Math.random() * (b - a);

/** Seeded RNG so the skyline/stars stay identical across resizes. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export class Renderer {
  readonly camera = new Camera();
  private ctx: CanvasRenderingContext2D;
  private sky: HTMLCanvasElement = document.createElement('canvas');
  private floor: HTMLCanvasElement = document.createElement('canvas');
  private width = 0;
  private height = 0;
  private dpr = 1;
  private crowd: Person[] = [];
  private motes: Mote[] = [];

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext('2d', { alpha: false })!;
  }

  resize(width: number, height: number): void {
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = width;
    this.height = height;
    this.canvas.width = Math.round(width * this.dpr);
    this.canvas.height = Math.round(height * this.dpr);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.camera.fit(width, height);
    this.buildSky();
    this.buildFloor();
    this.buildCrowd();
    this.buildMotes();
  }

  project(p: Vec3) {
    return this.camera.project(p);
  }

  /** Screen position after zoom (for DOM overlays that track the hoop). */
  hoopScreen(zoom = 1) {
    const h = this.camera.project(v3(0, WORLD.rimY, WORLD.hoopZ));
    return { x: h.x, y: h.y, zoom };
  }

  draw(view: SceneView): void {
    const { ctx, width: w, height: h } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;

    const hoop = this.camera.project(v3(0, WORLD.rimY, WORLD.hoopZ));
    const fx = hoop.x;
    const fy = hoop.y + (this.camera.project(WORLD.ballStart).y - hoop.y) * 0.25;

    // Background gets a fraction of the zoom: cheap parallax.
    ctx.save();
    ctx.translate(view.shakeX * 0.3, view.shakeY * 0.3);
    const bgZoom = 1 + (view.zoom - 1) * 0.3;
    ctx.translate(fx, fy);
    ctx.scale(bgZoom, bgZoom);
    ctx.translate(-fx, -fy);
    ctx.drawImage(this.sky, 0, 0, w, h);
    this.drawSkyLive(view);
    ctx.restore();

    ctx.save();
    ctx.translate(view.shakeX, view.shakeY);
    ctx.translate(fx, fy);
    ctx.scale(view.zoom, view.zoom);
    ctx.translate(-fx, -fy);
    ctx.drawImage(this.floor, 0, 0, w, h);
    this.drawFloorGlow(view);
    this.drawBeams(view);
    this.drawCables();
    this.drawBoard(view.boardGlow);
    this.drawGhostPath(view);
    this.drawTrail(view);

    const inside = (b: BallView | null) => {
      if (!b) return false;
      const dx = b.p.x;
      const dz = b.p.z - WORLD.hoopZ;
      return b.p.y < WORLD.rimY && b.p.y > WORLD.rimY - 0.75 && Math.hypot(dx, dz) < WORLD.rimR + 0.02;
    };
    this.drawShadow(view.ball);
    this.drawRim(view.rimShake, 'back');
    if (inside(view.ghost)) this.drawBall(view.ghost!);
    if (inside(view.ball)) this.drawBall(view.ball!);
    this.drawNet(view.net);
    this.drawRim(view.rimShake, 'front');
    if (view.ghost && !inside(view.ghost)) this.drawBall(view.ghost);
    if (view.ball && !inside(view.ball)) this.drawBall(view.ball);
    view.particles.draw(ctx);
    ctx.restore();

    this.drawCrowd(view);
    if (view.meter && view.ball) this.drawMeter(view.meter, view.ball);
    this.drawPost(view);
  }

  // ---------------------------------------------------------------- caches

  private buildSky(): void {
    const { width: w, height: h, dpr } = this;
    const c = this.sky;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const ctx = c.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const horizon = this.camera.horizonY;
    const r = rng(7);

    const sky = ctx.createLinearGradient(0, 0, 0, horizon);
    sky.addColorStop(0, '#020109');
    sky.addColorStop(0.45, '#0b0624');
    sky.addColorStop(0.8, '#260b47');
    sky.addColorStop(1, '#4f1060');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);

    // Nebula wash
    const neb = ctx.createRadialGradient(w * 0.18, horizon * 0.25, 0, w * 0.18, horizon * 0.25, w * 0.7);
    neb.addColorStop(0, 'rgba(61,252,255,0.10)');
    neb.addColorStop(1, 'rgba(61,252,255,0)');
    ctx.fillStyle = neb;
    ctx.fillRect(0, 0, w, horizon);
    const neb2 = ctx.createRadialGradient(w * 0.85, horizon * 0.15, 0, w * 0.85, horizon * 0.15, w * 0.6);
    neb2.addColorStop(0, 'rgba(255,43,214,0.12)');
    neb2.addColorStop(1, 'rgba(255,43,214,0)');
    ctx.fillStyle = neb2;
    ctx.fillRect(0, 0, w, horizon);

    // Stars
    const stars = Math.round((w * horizon) / 2600);
    for (let i = 0; i < stars; i++) {
      const x = r() * w;
      const y = Math.pow(r(), 1.4) * horizon * 0.85;
      const a = 0.25 + r() * 0.75;
      const s = r() < 0.08 ? 1.6 : 0.5 + r() * 0.8;
      ctx.fillStyle = `rgba(255,255,255,${a})`;
      ctx.beginPath();
      ctx.arc(x, y, s, 0, TAU);
      ctx.fill();
      if (s > 1.5) {
        ctx.strokeStyle = `rgba(200,240,255,${a * 0.5})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        ctx.moveTo(x - 5, y);
        ctx.lineTo(x + 5, y);
        ctx.moveTo(x, y - 5);
        ctx.lineTo(x, y + 5);
        ctx.stroke();
      }
    }

    // Synthwave sun
    const sunR = Math.min(w * 0.4, h * 0.24);
    const sx = w / 2;
    const sy = horizon - sunR * 0.12;
    const halo = ctx.createRadialGradient(sx, sy, sunR * 0.6, sx, sy, sunR * 2.6);
    halo.addColorStop(0, 'rgba(255,60,170,0.45)');
    halo.addColorStop(0.4, 'rgba(255,43,214,0.12)');
    halo.addColorStop(1, 'rgba(255,43,214,0)');
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, w, horizon + sunR);

    const sun = document.createElement('canvas');
    sun.width = Math.ceil(sunR * 2 * dpr);
    sun.height = Math.ceil(sunR * 2 * dpr);
    const sctx = sun.getContext('2d')!;
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const sg = sctx.createLinearGradient(0, 0, 0, sunR * 2);
    sg.addColorStop(0, '#fff3a1');
    sg.addColorStop(0.35, '#ffb347');
    sg.addColorStop(0.65, '#ff5a8a');
    sg.addColorStop(1, '#ff2bd6');
    sctx.fillStyle = sg;
    sctx.beginPath();
    sctx.arc(sunR, sunR, sunR, 0, TAU);
    sctx.fill();
    sctx.globalCompositeOperation = 'destination-out';
    for (let i = 0; i < 9; i++) {
      const t = i / 8;
      const y = sunR * (0.95 + t * 1.05);
      const band = 1 + t * sunR * 0.075;
      sctx.fillRect(0, y, sunR * 2, band);
    }
    ctx.drawImage(sun, sx - sunR, sy - sunR, sunR * 2, sunR * 2);

    // Skyline: two depth layers of towers with lit windows
    const layers = [
      { color: '#1b0d3a', rim: 'rgba(255,43,214,0.35)', min: 0.03, max: 0.11, win: 0.18 },
      { color: '#080418', rim: 'rgba(61,252,255,0.45)', min: 0.02, max: 0.075, win: 0.32 },
    ];
    for (const layer of layers) {
      let x = -20;
      while (x < w + 20) {
        const bw = w * (0.025 + r() * 0.06) + 14;
        const bh = h * (layer.min + r() * (layer.max - layer.min));
        const top = horizon - bh;
        ctx.fillStyle = layer.color;
        ctx.fillRect(x, top, bw, bh + 1);
        ctx.fillStyle = layer.rim;
        ctx.fillRect(x, top, bw, 1);
        if (r() < 0.25) {
          ctx.fillRect(x + bw * 0.5 - 0.5, top - bh * 0.25, 1, bh * 0.25);
          ctx.fillStyle = r() < 0.5 ? PALETTE.red : PALETTE.cyan;
          ctx.beginPath();
          ctx.arc(x + bw * 0.5, top - bh * 0.25, 1.6, 0, TAU);
          ctx.fill();
        }
        const cols = Math.max(1, Math.floor(bw / 7));
        const rows = Math.max(1, Math.floor(bh / 8));
        for (let cx = 0; cx < cols; cx++) {
          for (let cy = 0; cy < rows; cy++) {
            if (r() > layer.win) continue;
            const hue = r();
            ctx.fillStyle =
              hue < 0.45 ? 'rgba(61,252,255,0.55)' : hue < 0.8 ? 'rgba(255,43,214,0.5)' : 'rgba(255,210,63,0.6)';
            ctx.fillRect(x + 3 + cx * 7, top + 4 + cy * 8, 2.2, 3);
          }
        }
        x += bw + r() * 6;
      }
    }

    // Horizon line
    const hl = ctx.createLinearGradient(0, 0, w, 0);
    hl.addColorStop(0, 'rgba(255,43,214,0)');
    hl.addColorStop(0.5, 'rgba(255,120,230,0.95)');
    hl.addColorStop(1, 'rgba(255,43,214,0)');
    ctx.fillStyle = hl;
    ctx.fillRect(0, horizon - 1, w, 2);
  }

  private buildFloor(): void {
    const { width: w, height: h, dpr } = this;
    const c = this.floor;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const ctx = c.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const cam = this.camera;
    const horizon = cam.horizonY;
    const P = (x: number, z: number) => cam.project(v3(x, 0, z));

    const base = ctx.createLinearGradient(0, horizon, 0, h);
    base.addColorStop(0, '#1d0838');
    base.addColorStop(0.35, '#0d0526');
    base.addColorStop(1, '#05020f');
    ctx.fillStyle = base;
    ctx.fillRect(0, horizon, w, h - horizon);

    // Sun reflection on the floor
    const sunR = Math.min(w * 0.4, h * 0.24);
    const refl = ctx.createLinearGradient(0, horizon, 0, h);
    refl.addColorStop(0, 'rgba(255,90,170,0.38)');
    refl.addColorStop(0.5, 'rgba(255,43,214,0.08)');
    refl.addColorStop(1, 'rgba(255,43,214,0)');
    ctx.fillStyle = refl;
    ctx.beginPath();
    ctx.ellipse(w / 2, horizon, sunR * 0.9, (h - horizon) * 0.9, 0, 0, Math.PI);
    ctx.fill();

    // Neon grid
    const line = (a: { x: number; y: number }, b: { x: number; y: number }, color: string, width: number) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    };
    ctx.globalCompositeOperation = 'lighter';
    for (let x = -60; x <= 60; x += 2.4) {
      const a = P(x, 2.2);
      const b = P(x, 300);
      const fade = 1 - Math.min(1, Math.abs(x) / 60);
      line(a, b, `rgba(255,43,214,${0.1 * fade})`, 3);
      line(a, b, `rgba(255,110,230,${0.35 * fade})`, 1);
    }
    for (let i = 0; i < 26; i++) {
      const z = 2.2 + Math.pow(i, 1.7) * 0.9;
      const a = P(-80, z);
      const b = P(80, z);
      const fade = Math.max(0, 1 - i / 26);
      line(a, b, `rgba(255,43,214,${0.1 * fade})`, 3);
      line(a, b, `rgba(255,110,230,${0.32 * fade})`, 1);
    }
    ctx.globalCompositeOperation = 'source-over';

    // Court slab
    const baseline = WORLD.boardZ + 1.2;
    const half = 7.6;
    const quad = (pts: { x: number; y: number }[], fill: string) => {
      ctx.fillStyle = fill;
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.closePath();
      ctx.fill();
    };
    const slab = ctx.createLinearGradient(0, P(0, baseline).y, 0, h);
    slab.addColorStop(0, '#120a3a');
    slab.addColorStop(1, '#070420');
    quad([P(-half, baseline), P(half, baseline), P(half, 1.5), P(-half, 1.5)], slab as unknown as string);
    quad([P(-2.45, baseline), P(2.45, baseline), P(2.45, 1.5), P(-2.45, 1.5)], 'rgba(255,43,214,0.10)');

    const glowLine = (pts: { x: number; y: number }[], color: string, glow: string) => {
      ctx.lineJoin = 'round';
      for (const [wd, col] of [
        [7, glow],
        [3, glow],
        [1.4, color],
      ] as const) {
        ctx.strokeStyle = col;
        ctx.lineWidth = wd;
        ctx.beginPath();
        pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.stroke();
      }
    };
    ctx.globalCompositeOperation = 'lighter';
    glowLine([P(-half, 1.5), P(-half, baseline), P(half, baseline), P(half, 1.5)], '#bffcff', 'rgba(61,252,255,0.18)');
    glowLine([P(-2.45, 1.5), P(-2.45, baseline)], '#bffcff', 'rgba(61,252,255,0.16)');
    glowLine([P(2.45, 1.5), P(2.45, baseline)], '#bffcff', 'rgba(61,252,255,0.16)');
    const arcPts: { x: number; y: number }[] = [];
    for (let i = 0; i <= 32; i++) {
      const a = Math.PI + (i / 32) * Math.PI;
      arcPts.push(P(Math.cos(a) * 1.25, WORLD.hoopZ + Math.sin(a) * 1.25));
    }
    glowLine(arcPts, '#ffc2f3', 'rgba(255,43,214,0.16)');
    ctx.globalCompositeOperation = 'source-over';
  }

  private buildCrowd(): void {
    const { width: w } = this;
    const r = rng(42);
    this.crowd = [];
    const n = Math.max(12, Math.round(w / 34));
    for (let i = 0; i < n; i++) {
      const x = ((i + r() * 0.6) / n) * w;
      const edge = Math.abs(x - w / 2) / (w / 2);
      this.crowd.push({
        x,
        h: (0.55 + edge * 0.75) * (0.85 + r() * 0.3),
        w: 0.8 + r() * 0.4,
        phase: r() * TAU,
        phone: r() < 0.35,
        tint: r(),
      });
    }
  }

  private buildMotes(): void {
    this.motes = [];
    for (let i = 0; i < 46; i++) {
      this.motes.push({
        x: rand(0, this.width),
        y: rand(0, this.height * 0.85),
        vx: rand(-6, 6),
        vy: rand(-8, -2),
        r: rand(0.5, 1.6),
        a: rand(0.15, 0.5),
      });
    }
  }

  // ---------------------------------------------------------------- live layers

  private drawSkyLive(view: SceneView): void {
    const { ctx, width: w, height: h } = this;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const m of this.motes) {
      m.x += m.vx * 0.016;
      m.y += m.vy * 0.016;
      if (m.y < -4) {
        m.y = h * 0.85;
        m.x = rand(0, w);
      }
      if (m.x < -4) m.x = w + 4;
      if (m.x > w + 4) m.x = -4;
      const tw = 0.6 + 0.4 * Math.sin(view.time * 2 + m.x);
      ctx.fillStyle = `rgba(200,240,255,${m.a * tw})`;
      ctx.beginPath();
      ctx.arc(m.x, m.y, m.r, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  private drawBeams(view: SceneView): void {
    const { ctx, width: w, height: h } = this;
    const hoop = this.camera.project(v3(0, WORLD.rimY, WORLD.hoopZ));
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const beams = [
      { x: -w * 0.05, color: '61,252,255', phase: 0 },
      { x: w * 1.05, color: '255,43,214', phase: 2.1 },
    ];
    for (const b of beams) {
      const sway = Math.sin(view.time * 0.35 + b.phase) * w * 0.12;
      const tx = hoop.x + sway;
      const ty = hoop.y + h * 0.45;
      const spread = w * 0.22;
      const g = ctx.createLinearGradient(b.x, -20, tx, ty);
      g.addColorStop(0, `rgba(${b.color},${0.11 + view.hype * 0.12})`);
      g.addColorStop(1, `rgba(${b.color},0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(b.x, -20);
      ctx.lineTo(tx - spread, ty);
      ctx.lineTo(tx + spread, ty);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }

  private drawFloorGlow(view: SceneView): void {
    const { ctx } = this;
    const p = this.camera.project(v3(0, 0, WORLD.hoopZ));
    const s = p.s;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, s * 2.2);
    g.addColorStop(0, `rgba(255,122,26,${0.14 + view.boardGlow * 0.2})`);
    g.addColorStop(1, 'rgba(255,122,26,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(p.x, p.y, s * 2.2, s * 0.7, 0, 0, TAU);
    ctx.fill();
    ctx.restore();
  }

  /** The board hangs from the rafters on two cables. */
  private drawCables(): void {
    const { ctx } = this;
    const cam = this.camera;
    ctx.save();
    for (const x of [-0.62, 0.62]) {
      const top = cam.project(v3(x * 1.4, 14, WORLD.boardZ + 0.4));
      const end = cam.project(v3(x, WORLD.boardTop, WORLD.boardZ));
      ctx.strokeStyle = 'rgba(10,6,30,0.9)';
      ctx.lineWidth = Math.max(1.5, 0.018 * end.s);
      ctx.beginPath();
      ctx.moveTo(top.x, top.y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();
      ctx.strokeStyle = 'rgba(61,252,255,0.28)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawBoard(glow: number): void {
    const { ctx } = this;
    const cam = this.camera;
    const hw = WORLD.boardW / 2;
    const z = WORLD.boardZ;
    const tl = cam.project(v3(-hw, WORLD.boardTop, z));
    const tr = cam.project(v3(hw, WORLD.boardTop, z));
    const br = cam.project(v3(hw, WORLD.boardBottom, z));
    const bl = cam.project(v3(-hw, WORLD.boardBottom, z));
    const s = tl.s;

    const path = (pts: { x: number; y: number }[]) => {
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.closePath();
    };

    // Halo behind the board
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const cx = (tl.x + tr.x) / 2;
    const cy = (tl.y + bl.y) / 2;
    const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, (tr.x - tl.x) * 0.9);
    halo.addColorStop(0, `rgba(255,43,214,${0.18 + glow * 0.35})`);
    halo.addColorStop(1, 'rgba(255,43,214,0)');
    ctx.fillStyle = halo;
    ctx.fillRect(cx - (tr.x - tl.x), cy - (tr.x - tl.x), (tr.x - tl.x) * 2, (tr.x - tl.x) * 2);
    ctx.restore();

    // Glass
    const glass = ctx.createLinearGradient(0, tl.y, 0, bl.y);
    glass.addColorStop(0, 'rgba(90,150,255,0.20)');
    glass.addColorStop(1, 'rgba(255,43,214,0.14)');
    path([tl, tr, br, bl]);
    ctx.fillStyle = glass;
    ctx.fill();
    // Reflection streak
    ctx.save();
    path([tl, tr, br, bl]);
    ctx.clip();
    ctx.fillStyle = 'rgba(255,255,255,0.07)';
    ctx.beginPath();
    ctx.moveTo(tl.x + (tr.x - tl.x) * 0.15, tl.y);
    ctx.lineTo(tl.x + (tr.x - tl.x) * 0.32, tl.y);
    ctx.lineTo(tl.x + (tr.x - tl.x) * 0.12, bl.y);
    ctx.lineTo(tl.x - (tr.x - tl.x) * 0.05, bl.y);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineJoin = 'round';
    const lw = Math.max(1.5, 0.022 * s);
    const bright = 0.75 + glow * 0.25;
    for (const [mult, col] of [
      [5, `rgba(255,43,214,${0.12 * bright})`],
      [2.4, `rgba(255,43,214,${0.4 * bright})`],
      [1, `rgba(255,190,245,${bright})`],
    ] as const) {
      path([tl, tr, br, bl]);
      ctx.strokeStyle = col;
      ctx.lineWidth = lw * mult;
      ctx.stroke();
    }
    // Shooter's square
    const iw = 0.3;
    const ib = WORLD.rimY + 0.16;
    const it = ib + 0.45;
    const q = [
      cam.project(v3(-iw, it, z)),
      cam.project(v3(iw, it, z)),
      cam.project(v3(iw, ib, z)),
      cam.project(v3(-iw, ib, z)),
    ];
    for (const [mult, col] of [
      [4, `rgba(61,252,255,${0.14 * bright})`],
      [2, `rgba(61,252,255,${0.4 * bright})`],
      [0.8, `rgba(220,255,255,${bright})`],
    ] as const) {
      path(q);
      ctx.strokeStyle = col;
      ctx.lineWidth = lw * mult;
      ctx.stroke();
    }
    ctx.restore();

    // Bracket from board to rim
    const b1 = cam.project(v3(-0.08, WORLD.rimY + 0.02, z));
    const b2 = cam.project(v3(0.08, WORLD.rimY - 0.06, WORLD.hoopZ + WORLD.rimR));
    ctx.fillStyle = '#1a1036';
    ctx.fillRect(Math.min(b1.x, b2.x), Math.min(b1.y, b2.y), Math.abs(b2.x - b1.x) || 4, Math.abs(b2.y - b1.y) + 3);
  }

  private rimGeometry(shake: number) {
    const cam = this.camera;
    const c = cam.project(v3(0, WORLD.rimY, WORLD.hoopZ));
    const front = cam.project(v3(0, WORLD.rimY, WORLD.hoopZ - WORLD.rimR));
    const back = cam.project(v3(0, WORLD.rimY, WORLD.hoopZ + WORLD.rimR));
    const rx = WORLD.rimR * c.s;
    const ry = Math.max(2, (front.y - back.y) / 2);
    const wob = Math.sin(performance.now() / 22) * shake * c.s * 0.02;
    return { x: c.x, y: (front.y + back.y) / 2 + wob, rx, ry, s: c.s };
  }

  private drawRim(shake: number, half: 'back' | 'front'): void {
    const { ctx } = this;
    const g = this.rimGeometry(shake);
    const lw = Math.max(2.5, 0.03 * g.s);
    const [a0, a1] = half === 'back' ? [Math.PI, TAU] : [0, Math.PI];
    ctx.save();
    ctx.lineCap = 'round';
    ctx.globalCompositeOperation = 'lighter';
    ctx.strokeStyle = 'rgba(255,106,0,0.22)';
    ctx.lineWidth = lw * 4;
    ctx.beginPath();
    ctx.ellipse(g.x, g.y, g.rx, g.ry, 0, a0, a1);
    ctx.stroke();
    ctx.globalCompositeOperation = 'source-over';
    ctx.strokeStyle = half === 'back' ? '#c84b00' : '#ff6a00';
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.ellipse(g.x, g.y, g.rx, g.ry, 0, a0, a1);
    ctx.stroke();
    if (half === 'front') {
      ctx.strokeStyle = 'rgba(255,220,170,0.9)';
      ctx.lineWidth = Math.max(1, lw * 0.3);
      ctx.beginPath();
      ctx.ellipse(g.x, g.y - lw * 0.25, g.rx, g.ry, 0, 0.15, Math.PI - 0.15);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawNet(net: Net): void {
    const { ctx } = this;
    const cam = this.camera;
    const pts: { x: number; y: number; z: number }[][] = [];
    for (let r = 0; r < Net.ROWS; r++) {
      const row: { x: number; y: number; z: number }[] = [];
      for (let c = 0; c < Net.COLS; c++) {
        const wp = net.world(r, c);
        const p = cam.project(wp);
        row.push({ x: p.x, y: p.y, z: wp.z });
      }
      pts.push(row);
    }
    const s = cam.project(v3(0, WORLD.rimY, WORLD.hoopZ)).s;
    const lw = Math.max(0.8, 0.0075 * s);
    ctx.save();
    ctx.lineCap = 'round';
    for (const pass of ['back', 'front'] as const) {
      ctx.beginPath();
      for (let r = 1; r < Net.ROWS; r++) {
        for (let c = 0; c < Net.COLS; c++) {
          const a = pts[r - 1][c];
          const odd = r % 2 === 1;
          const n1 = pts[r][c];
          const n2 = pts[r][(c + (odd ? -1 : 1) + Net.COLS) % Net.COLS];
          for (const b of [n1, n2]) {
            const isBack = (a.z + b.z) / 2 > WORLD.hoopZ;
            if ((pass === 'back') !== isBack) continue;
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
          }
        }
      }
      ctx.globalCompositeOperation = 'lighter';
      ctx.strokeStyle = pass === 'back' ? 'rgba(61,252,255,0.08)' : 'rgba(61,252,255,0.16)';
      ctx.lineWidth = lw * 3.5;
      ctx.stroke();
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = pass === 'back' ? 'rgba(190,200,235,0.45)' : 'rgba(240,248,255,0.92)';
      ctx.lineWidth = lw;
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawShadow(ball: BallView | null): void {
    if (!ball) return;
    const { ctx } = this;
    const p = this.camera.project(v3(ball.p.x, 0, ball.p.z));
    if (p.y > this.height + 40) return;
    const height = Math.max(0, ball.p.y);
    const k = Math.max(0, 1 - height / 4.5);
    const r = WORLD.ballR * p.s * (1.3 + (1 - k));
    ctx.save();
    ctx.globalAlpha = 0.45 * k * ball.alpha;
    const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
    g.addColorStop(0, 'rgba(0,0,0,0.9)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(p.x, p.y, r, r * 0.35, 0, 0, TAU);
    ctx.fill();
    ctx.restore();
  }

  private drawTrail(view: SceneView): void {
    const pts = view.trail;
    if (pts.length < 2) return;
    const { ctx } = this;
    const cam = this.camera;
    const proj = pts.map((t) => ({ ...cam.project(t.p), age: t.age }));
    const fire = !!view.ball?.fire;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    for (let i = 1; i < proj.length; i++) {
      const a = proj[i - 1];
      const b = proj[i];
      const life = Math.max(0, 1 - b.age / 0.32);
      if (life <= 0) continue;
      const r = WORLD.ballR * b.s;
      const [cr, cg, cb] = fire ? [255, 140 + 80 * life, 40] : [255, 90 + 120 * life, 200 - 120 * life];
      ctx.strokeStyle = `rgba(${cr},${cg | 0},${cb | 0},${0.28 * life})`;
      ctx.lineWidth = r * 2.1 * life;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.strokeStyle = `rgba(255,240,220,${0.5 * life})`;
      ctx.lineWidth = Math.max(1, r * 0.5 * life);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawGhostPath(view: SceneView): void {
    if (!view.ghost || view.ghostPath.length < 2) return;
    const { ctx } = this;
    const cam = this.camera;
    const n = Math.floor(view.ghostPath.length * Math.min(1, view.ghostReveal));
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.setLineDash([2, 7]);
    ctx.lineCap = 'round';
    ctx.strokeStyle = `rgba(61,252,255,${0.75 * view.ghost.alpha})`;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const p = cam.project(view.ghostPath[i]);
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  private drawBall(b: BallView): void {
    const { ctx } = this;
    const p = this.camera.project(b.p);
    const r = WORLD.ballR * p.s;
    if (p.y - r > this.height + 10) return;
    ctx.save();
    ctx.globalAlpha = b.alpha;

    if (b.ghost) {
      ctx.globalCompositeOperation = 'lighter';
      const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 2.4);
      g.addColorStop(0, 'rgba(61,252,255,0.35)');
      g.addColorStop(1, 'rgba(61,252,255,0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r * 2.4, 0, TAU);
      ctx.fill();
      ctx.fillStyle = 'rgba(61,252,255,0.18)';
      ctx.strokeStyle = 'rgba(180,255,255,0.95)';
      ctx.lineWidth = Math.max(1.2, r * 0.09);
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, TAU);
      ctx.fill();
      ctx.stroke();
      this.seams(p.x, p.y, r, b.spin, 'rgba(180,255,255,0.6)');
      ctx.restore();
      return;
    }

    // Outer glow
    ctx.globalCompositeOperation = 'lighter';
    const glow = ctx.createRadialGradient(p.x, p.y, r * 0.8, p.x, p.y, r * (b.fire ? 2.6 : 1.8));
    glow.addColorStop(0, b.fire ? 'rgba(255,160,40,0.55)' : 'rgba(255,122,26,0.28)');
    glow.addColorStop(1, 'rgba(255,122,26,0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r * (b.fire ? 2.6 : 1.8), 0, TAU);
    ctx.fill();

    ctx.globalCompositeOperation = 'source-over';
    const body = ctx.createRadialGradient(p.x - r * 0.35, p.y - r * 0.4, r * 0.1, p.x, p.y, r);
    body.addColorStop(0, '#ffb877');
    body.addColorStop(0.45, '#ff7417');
    body.addColorStop(1, '#7a2200');
    ctx.fillStyle = body;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, TAU);
    ctx.fill();
    this.seams(p.x, p.y, r, b.spin, 'rgba(35,10,0,0.85)');

    // Neon rim lights
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineWidth = Math.max(1, r * 0.12);
    ctx.strokeStyle = 'rgba(61,252,255,0.75)';
    ctx.beginPath();
    ctx.arc(p.x, p.y, r * 0.94, Math.PI * 0.62, Math.PI * 1.25);
    ctx.stroke();
    ctx.strokeStyle = 'rgba(255,43,214,0.7)';
    ctx.beginPath();
    ctx.arc(p.x, p.y, r * 0.94, -Math.PI * 0.35, Math.PI * 0.25);
    ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.beginPath();
    ctx.ellipse(p.x - r * 0.38, p.y - r * 0.45, r * 0.28, r * 0.16, -0.6, 0, TAU);
    ctx.fill();
    ctx.restore();
  }

  private seams(x: number, y: number, r: number, spin: number, color: string): void {
    const { ctx } = this;
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.clip();
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(0.8, r * 0.07);
    const s = Math.sin(spin);
    const c = Math.cos(spin);
    ctx.beginPath();
    ctx.ellipse(x, y + c * r * 0.08, r, Math.abs(s) * r + 0.5, 0, 0, TAU);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x, y + r);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x - r * 1.28, y + s * r * 0.15, r * 0.92, -0.9, 0.9);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x + r * 1.28, y - s * r * 0.15, r * 0.92, Math.PI - 0.9, Math.PI + 0.9);
    ctx.stroke();
    ctx.restore();
  }

  private drawCrowd(view: SceneView): void {
    const { ctx, width: w, height: h } = this;
    const portrait = h > w * 1.05;
    const unit = portrait ? Math.min(w, h) * 0.13 : h * 0.085;
    ctx.save();
    for (const p of this.crowd) {
      const bob = Math.sin(view.time * (2.2 + p.tint) + p.phase) * unit * 0.03;
      const jump = view.hype * unit * 0.35 * Math.abs(Math.sin(view.time * 9 + p.phase));
      const height = p.h * unit;
      const headR = unit * 0.16 * p.w;
      const top = h - height - bob - jump;
      const shoulderW = headR * 2.6;
      ctx.fillStyle = '#06030f';
      ctx.beginPath();
      ctx.ellipse(p.x, top + headR * 2.9, shoulderW, headR * 1.6, 0, Math.PI, TAU);
      ctx.lineTo(p.x + shoulderW, h + 10);
      ctx.lineTo(p.x - shoulderW, h + 10);
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.arc(p.x, top + headR, headR, 0, TAU);
      ctx.fill();
      // Rim light from the court
      ctx.strokeStyle = p.x < w / 2 ? 'rgba(61,252,255,0.35)' : 'rgba(255,43,214,0.35)';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(p.x, top + headR, headR, Math.PI * 1.1, Math.PI * 1.9);
      ctx.stroke();
      if (p.phone && (view.hype > 0.2 || Math.sin(view.time * 0.7 + p.phase * 3) > 0.2)) {
        const px = p.x + headR * 1.6;
        const py = top - headR * 0.6;
        ctx.fillStyle = '#0b0820';
        ctx.fillRect(px - 1, py, 2, headR * 2);
        ctx.fillStyle = 'rgba(210,240,255,0.9)';
        ctx.fillRect(px - headR * 0.35, py - headR * 0.6, headR * 0.7, headR * 1.1);
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        const flash = view.hype > 0.4 && Math.sin(view.time * 23 + p.phase * 7) > 0.85;
        const g = ctx.createRadialGradient(px, py, 0, px, py, headR * (flash ? 5 : 2.2));
        g.addColorStop(0, flash ? 'rgba(255,255,255,0.85)' : 'rgba(180,230,255,0.35)');
        g.addColorStop(1, 'rgba(180,230,255,0)');
        ctx.fillStyle = g;
        ctx.fillRect(px - headR * 5, py - headR * 5, headR * 10, headR * 10);
        ctx.restore();
      }
    }
    ctx.restore();
  }

  private drawMeter(m: MeterView, ball: BallView): void {
    const { ctx } = this;
    const p = this.camera.project(ball.p);
    const r = Math.max(44, WORLD.ballR * p.s * 1.75);
    const a0 = Math.PI * 0.75;
    const sweep = Math.PI * 1.5;
    const at = (f: number) => a0 + sweep * Math.max(0, Math.min(1, f));
    const lw = Math.max(6, r * 0.13);
    ctx.save();
    ctx.globalAlpha = m.alpha;
    ctx.lineCap = 'round';
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, a0, a0 + sweep);
    ctx.stroke();

    ctx.globalCompositeOperation = 'lighter';
    ctx.strokeStyle = 'rgba(77,255,154,0.28)';
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, at(m.perfect - m.makeHalf), at(m.perfect + m.makeHalf));
    ctx.stroke();
    ctx.strokeStyle = 'rgba(77,255,154,0.35)';
    ctx.lineWidth = lw * 2.2;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, at(m.perfect - m.swishHalf), at(m.perfect + m.swishHalf));
    ctx.stroke();
    ctx.strokeStyle = '#4dff9a';
    ctx.lineWidth = lw;
    ctx.stroke();

    const inZone = Math.abs(m.fraction - m.perfect) <= m.swishHalf;
    const past = m.fraction > m.perfect + m.makeHalf;
    const fillColor = inZone ? '#bfffdc' : past ? '#ff3b5c' : '#ffb347';
    ctx.globalCompositeOperation = 'source-over';
    ctx.strokeStyle = fillColor;
    ctx.lineWidth = lw * 0.55;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, a0, at(m.fraction));
    ctx.stroke();

    const na = at(m.fraction);
    const nx = p.x + Math.cos(na) * r;
    const ny = p.y + Math.sin(na) * r;
    ctx.globalCompositeOperation = 'lighter';
    const g = ctx.createRadialGradient(nx, ny, 0, nx, ny, lw * 2.6);
    g.addColorStop(0, 'rgba(255,255,255,0.9)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(nx, ny, lw * 2.6, 0, TAU);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(nx, ny, lw * 0.6, 0, TAU);
    ctx.fill();
    ctx.restore();
  }

  private drawPost(view: SceneView): void {
    const { ctx, width: w, height: h } = this;
    ctx.save();
    const vig = ctx.createRadialGradient(w / 2, h * 0.45, Math.min(w, h) * 0.35, w / 2, h * 0.5, Math.max(w, h) * 0.8);
    vig.addColorStop(0, 'rgba(0,0,0,0)');
    vig.addColorStop(1, `rgba(0,0,0,${0.45 + view.slowmo * 0.3})`);
    ctx.fillStyle = vig;
    ctx.fillRect(0, 0, w, h);

    if (view.slowmo > 0.01) {
      const bar = h * 0.055 * view.slowmo;
      ctx.fillStyle = 'rgba(0,0,0,0.85)';
      ctx.fillRect(0, 0, w, bar);
      ctx.fillRect(0, h - bar, w, bar);
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = `rgba(61,252,255,${0.05 * view.slowmo})`;
      ctx.fillRect(0, 0, w, h);
    }
    if (view.flash > 0.01) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = `rgba(255,255,255,${view.flash * 0.22})`;
      ctx.fillRect(0, 0, w, h);
    }
    ctx.restore();
  }
}
