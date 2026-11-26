export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export const v3 = (x: number, y: number, z: number): Vec3 => ({ x, y, z });

/** World units are metres. x = right, y = up, z = away from the shooter. */
export const WORLD = {
  gravity: 12,
  rimY: 3.05,
  hoopZ: 4.2,
  rimR: 0.23,
  ballR: 0.12,
  boardZ: 4.58,
  boardW: 1.83,
  boardBottom: 2.9,
  boardTop: 3.97,
  ballStart: v3(0, 1.5, 0.3),
} as const;

export interface Projected {
  x: number;
  y: number;
  /** pixels per metre at this depth */
  s: number;
}

/**
 * Telephoto camera behind the shooter. A local shear around the hoop tilts the rim
 * toward the viewer so the opening reads as an ellipse, the way arcade games cheat it.
 */
export class Camera {
  /** Slightly left of the shooter so the arc reads as a curve instead of a vertical line. */
  readonly camX = -0.55;
  readonly camY = 2.3;
  readonly camZ = -5.2;
  readonly tilt = 0.3;
  readonly shearSpan = 0.7;

  f = 1000;
  cx = 0;
  cy = 0;
  width = 0;
  height = 0;

  fit(width: number, height: number): void {
    this.width = width;
    this.height = height;
    const portrait = height > width * 1.05;
    const hoopTarget = portrait ? 0.34 : 0.37;
    const ballTarget = portrait ? 0.84 : 0.8;

    const hoop = this.normalised(v3(0, WORLD.rimY, WORLD.hoopZ));
    const ball = this.normalised(WORLD.ballStart);
    let f = ((ballTarget - hoopTarget) * height) / (hoop - ball);
    // Keep the rim from overpowering very wide-short or very narrow screens.
    const rimPx = (WORLD.rimR * 2 * f) / (WORLD.hoopZ - this.camZ);
    const maxRim = width * (portrait ? 0.3 : 0.16);
    if (rimPx > maxRim) f *= maxRim / rimPx;
    this.f = f;
    const hoopDepth = WORLD.hoopZ - this.camZ;
    this.cx = width / 2 + (this.camX * f) / hoopDepth;
    this.cy = hoopTarget * height + f * hoop;
  }

  project(p: Vec3): Projected {
    const d = Math.max(0.2, p.z - this.camZ);
    const s = this.f / d;
    return {
      x: this.cx + (p.x - this.camX) * s,
      y: this.cy - (p.y - this.camY + this.shear(p.z)) * s,
      s,
    };
  }

  /** Screen y of the floor vanishing line (the shear saturates, so it is `cy`). */
  get horizonY(): number {
    return this.cy;
  }

  private shear(z: number): number {
    return this.tilt * this.shearSpan * Math.tanh((z - WORLD.hoopZ) / this.shearSpan);
  }

  private normalised(p: Vec3): number {
    return (p.y - this.camY + this.shear(p.z)) / (p.z - this.camZ);
  }
}
