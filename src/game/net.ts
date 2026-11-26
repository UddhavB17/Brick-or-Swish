import { WORLD, v3, type Vec3 } from './world';

const COLS = 14;
const ROWS = 5;
const LENGTH = 0.46;

interface Node {
  rest: Vec3;
  off: Vec3;
  vel: Vec3;
}

/** Spring-damped net mesh in hoop-local coordinates (origin = rim centre). */
export class Net {
  readonly nodes: Node[][] = [];

  constructor() {
    for (let r = 0; r < ROWS; r++) {
      const row: Node[] = [];
      const radius = WORLD.rimR * (1 - 0.36 * (r / (ROWS - 1)));
      for (let c = 0; c < COLS; c++) {
        const a = ((c + (r % 2) * 0.5) / COLS) * Math.PI * 2;
        row.push({
          rest: v3(Math.cos(a) * radius, -(r / (ROWS - 1)) * LENGTH, Math.sin(a) * radius),
          off: v3(0, 0, 0),
          vel: v3(0, 0, 0),
        });
      }
      this.nodes.push(row);
    }
  }

  update(dt: number, ball: Vec3 | null): void {
    const k = 210;
    const damp = 10;
    for (let r = 1; r < ROWS; r++) {
      for (const n of this.nodes[r]) {
        n.vel.x += (-k * n.off.x - damp * n.vel.x) * dt;
        n.vel.y += (-k * n.off.y - damp * n.vel.y) * dt;
        n.vel.z += (-k * n.off.z - damp * n.vel.z) * dt;
        n.off.x += n.vel.x * dt;
        n.off.y += n.vel.y * dt;
        n.off.z += n.vel.z * dt;
      }
    }
    if (!ball) return;
    const lx = ball.x;
    const ly = ball.y - WORLD.rimY;
    const lz = ball.z - WORLD.hoopZ;
    if (ly > 0.1 || ly < -LENGTH - 0.15) return;
    const reach = WORLD.ballR + 0.015;
    for (let r = 1; r < ROWS; r++) {
      for (const n of this.nodes[r]) {
        const px = n.rest.x + n.off.x;
        const py = n.rest.y + n.off.y;
        const pz = n.rest.z + n.off.z;
        const dx = px - lx;
        const dy = py - ly;
        const dz = pz - lz;
        const d = Math.hypot(dx, dy, dz);
        if (d < reach && d > 1e-4) {
          const push = (reach - d) / d;
          n.off.x += dx * push * 0.9;
          n.off.z += dz * push * 0.9;
          n.off.y += Math.min(0, dy * push) - 0.01;
          n.vel.y -= 0.6;
        }
      }
    }
  }

  /** Rim hit: shiver the net. */
  jiggle(strength: number): void {
    for (let r = 1; r < ROWS; r++) {
      for (const n of this.nodes[r]) {
        n.vel.x += (Math.random() - 0.5) * strength * 1.4;
        n.vel.y += (Math.random() - 0.5) * strength * 0.6;
        n.vel.z += (Math.random() - 0.5) * strength * 1.4;
      }
    }
  }

  /** Swish: the net snaps down and flares. */
  snap(strength: number): void {
    for (let r = 1; r < ROWS; r++) {
      for (const n of this.nodes[r]) {
        const f = r / (ROWS - 1);
        n.vel.y -= strength * 1.8 * f;
        n.vel.x += n.rest.x * strength * 5 * f;
        n.vel.z += n.rest.z * strength * 5 * f;
      }
    }
  }

  world(r: number, c: number): Vec3 {
    const n = this.nodes[r][((c % COLS) + COLS) % COLS];
    return v3(n.rest.x + n.off.x, WORLD.rimY + n.rest.y + n.off.y, WORLD.hoopZ + n.rest.z + n.off.z);
  }

  static readonly COLS = COLS;
  static readonly ROWS = ROWS;
}
