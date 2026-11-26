export type ParticleKind = 'spark' | 'ring' | 'confetti' | 'puff' | 'ember' | 'mote';

export interface Particle {
  kind: ParticleKind;
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  size: number;
  color: string;
  spin: number;
  angle: number;
  drag: number;
  gravity: number;
}

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <T>(arr: readonly T[]) => arr[Math.floor(Math.random() * arr.length)];

const SWISH_COLORS = ['#3dfcff', '#9bfff4', '#ffffff', '#ffd23f'] as const;
const CLANG_COLORS = ['#ffb347', '#ff7a1a', '#ffe08a'] as const;
const CONFETTI = ['#3dfcff', '#ff2bd6', '#ffd23f', '#4dff9a', '#ffffff'] as const;

/** Screen-space particle pool (pixels). */
export class Particles {
  readonly list: Particle[] = [];

  private add(p: Partial<Particle> & Pick<Particle, 'kind' | 'x' | 'y'>): void {
    if (this.list.length > 600) this.list.shift();
    this.list.push({
      vx: 0,
      vy: 0,
      life: 0,
      max: 1,
      size: 2,
      color: '#fff',
      spin: 0,
      angle: 0,
      drag: 0.9,
      gravity: 0,
      ...p,
    });
  }

  swish(x: number, y: number, scale: number): void {
    this.add({ kind: 'ring', x, y, max: 0.55, size: scale * 0.3, color: '#3dfcff' });
    for (let i = 0; i < 34; i++) {
      const a = rand(0, Math.PI * 2);
      const sp = rand(0.6, 2.6) * scale;
      this.add({
        kind: 'spark',
        x,
        y,
        vx: Math.cos(a) * sp,
        vy: Math.sin(a) * sp * 0.55 - scale * 0.6,
        max: rand(0.45, 0.95),
        size: rand(1.2, 2.8) * (scale / 120),
        color: pick(SWISH_COLORS),
        drag: 0.9,
        gravity: scale * 3,
      });
    }
  }

  clang(x: number, y: number, scale: number, strength: number): void {
    const n = Math.round(10 + strength * 18);
    for (let i = 0; i < n; i++) {
      const a = rand(Math.PI * 1.05, Math.PI * 1.95);
      const sp = rand(0.6, 2.2) * scale * (0.5 + strength);
      this.add({
        kind: 'spark',
        x,
        y,
        vx: Math.cos(a) * sp,
        vy: Math.sin(a) * sp,
        max: rand(0.25, 0.55),
        size: rand(1, 2.2) * (scale / 120),
        color: pick(CLANG_COLORS),
        drag: 0.86,
        gravity: scale * 5,
      });
    }
    this.add({ kind: 'ring', x, y, max: 0.35, size: scale * 0.18 * (0.6 + strength), color: '#ffb347' });
  }

  puff(x: number, y: number, scale: number): void {
    for (let i = 0; i < 10; i++) {
      const a = rand(0, Math.PI * 2);
      this.add({
        kind: 'puff',
        x,
        y,
        vx: Math.cos(a) * scale * rand(0.2, 0.7),
        vy: Math.sin(a) * scale * rand(0.1, 0.4),
        max: rand(0.5, 0.9),
        size: scale * rand(0.06, 0.12),
        color: 'rgba(200,190,255,0.35)',
        drag: 0.9,
      });
    }
  }

  confetti(width: number, height: number): void {
    for (let i = 0; i < 160; i++) {
      this.add({
        kind: 'confetti',
        x: rand(0, width),
        y: rand(-height * 0.4, -10),
        vx: rand(-40, 40),
        vy: rand(120, 320),
        max: rand(2.2, 3.6),
        size: rand(4, 9),
        color: pick(CONFETTI),
        spin: rand(-8, 8),
        angle: rand(0, 6),
        drag: 0.995,
        gravity: 60,
      });
    }
  }

  ember(x: number, y: number, scale: number): void {
    this.add({
      kind: 'ember',
      x: x + rand(-0.3, 0.3) * scale * 0.12,
      y: y + rand(-0.3, 0.3) * scale * 0.12,
      vx: rand(-20, 20),
      vy: rand(-60, -20),
      max: rand(0.3, 0.6),
      size: rand(0.06, 0.12) * scale,
      color: pick(['#ffd23f', '#ff7a1a', '#ff3b5c'] as const),
      drag: 0.92,
    });
  }

  update(dt: number): void {
    for (let i = this.list.length - 1; i >= 0; i--) {
      const p = this.list[i];
      p.life += dt;
      if (p.life >= p.max) {
        this.list.splice(i, 1);
        continue;
      }
      const drag = Math.pow(p.drag, dt * 60);
      p.vx *= drag;
      p.vy = p.vy * drag + p.gravity * dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.angle += p.spin * dt;
    }
  }

  draw(ctx: CanvasRenderingContext2D): void {
    ctx.save();
    for (const p of this.list) {
      const t = p.life / p.max;
      const a = 1 - t;
      switch (p.kind) {
        case 'spark':
        case 'ember': {
          ctx.globalCompositeOperation = 'lighter';
          ctx.globalAlpha = a;
          ctx.fillStyle = p.color;
          const r = p.kind === 'ember' ? p.size * (1 - t * 0.6) : p.size;
          ctx.beginPath();
          ctx.arc(p.x, p.y, Math.max(0.5, r), 0, Math.PI * 2);
          ctx.fill();
          if (p.kind === 'spark') {
            ctx.globalAlpha = a * 0.5;
            ctx.strokeStyle = p.color;
            ctx.lineWidth = Math.max(0.5, r * 0.8);
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p.x - p.vx * 0.03, p.y - p.vy * 0.03);
            ctx.stroke();
          }
          break;
        }
        case 'ring': {
          ctx.globalCompositeOperation = 'lighter';
          ctx.globalAlpha = a * 0.8;
          ctx.strokeStyle = p.color;
          ctx.lineWidth = Math.max(1, 3 * a);
          ctx.beginPath();
          ctx.ellipse(p.x, p.y, p.size * (1 + t * 2.4), p.size * 0.35 * (1 + t * 2.4), 0, 0, Math.PI * 2);
          ctx.stroke();
          break;
        }
        case 'puff': {
          ctx.globalCompositeOperation = 'source-over';
          ctx.globalAlpha = a * 0.6;
          ctx.fillStyle = p.color;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size * (1 + t * 1.5), 0, Math.PI * 2);
          ctx.fill();
          break;
        }
        case 'confetti': {
          ctx.globalCompositeOperation = 'source-over';
          ctx.globalAlpha = Math.min(1, a * 2);
          ctx.fillStyle = p.color;
          ctx.save();
          ctx.translate(p.x, p.y);
          ctx.rotate(p.angle);
          ctx.scale(1, Math.abs(Math.cos(p.angle * 1.7)) + 0.15);
          ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
          ctx.restore();
          break;
        }
        case 'mote':
          break;
      }
    }
    ctx.restore();
  }
}
