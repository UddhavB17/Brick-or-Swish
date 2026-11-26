const MUTE_KEY = 'bos_muted';

/** All sounds are synthesised at runtime: zero audio assets to download. */
export class Sfx {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private noise: AudioBuffer | null = null;
  private ambience: GainNode | null = null;
  muted = localStorage.getItem(MUTE_KEY) === '1';

  /** Must run inside a user gesture (iOS). */
  unlock(): void {
    if (!this.ctx) {
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return;
      this.ctx = new Ctor();
      const comp = this.ctx.createDynamicsCompressor();
      comp.threshold.value = -14;
      comp.ratio.value = 4;
      this.master = this.ctx.createGain();
      this.master.gain.value = this.muted ? 0 : 0.9;
      this.master.connect(comp).connect(this.ctx.destination);
      this.noise = this.makeNoise(2);
      this.startAmbience();
    }
    if (this.ctx.state === 'suspended') void this.ctx.resume();
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    localStorage.setItem(MUTE_KEY, muted ? '1' : '0');
    if (this.master && this.ctx) this.master.gain.setTargetAtTime(muted ? 0 : 0.9, this.ctx.currentTime, 0.05);
  }

  private makeNoise(seconds: number): AudioBuffer {
    const ctx = this.ctx!;
    const buf = ctx.createBuffer(1, ctx.sampleRate * seconds, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    return buf;
  }

  private noiseSource(): AudioBufferSourceNode {
    const src = this.ctx!.createBufferSource();
    src.buffer = this.noise;
    src.loop = true;
    return src;
  }

  private get ready(): boolean {
    return !!this.ctx && !!this.master && this.ctx.state === 'running';
  }

  private startAmbience(): void {
    const ctx = this.ctx!;
    const src = this.noiseSource();
    const lp = ctx.createBiquadFilter();
    lp.type = 'bandpass';
    lp.frequency.value = 520;
    lp.Q.value = 0.6;
    this.ambience = ctx.createGain();
    this.ambience.gain.value = 0.035;
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.frequency.value = 0.23;
    lfoGain.gain.value = 0.012;
    lfo.connect(lfoGain).connect(this.ambience.gain);
    src.connect(lp).connect(this.ambience).connect(this.master!);
    src.start();
    lfo.start();
  }

  private env(gain: GainNode, t: number, peak: number, attack: number, decay: number): void {
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(peak, t + attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
  }

  tick(progress: number): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const gn = ctx.createGain();
    o.type = 'sine';
    o.frequency.value = 520 + progress * 900;
    this.env(gn, t, 0.05, 0.003, 0.05);
    o.connect(gn).connect(this.master!);
    o.start(t);
    o.stop(t + 0.08);
  }

  zone(): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    [1320, 1980].forEach((f, i) => {
      const o = ctx.createOscillator();
      const gn = ctx.createGain();
      o.type = 'triangle';
      o.frequency.value = f;
      this.env(gn, t + i * 0.03, 0.06, 0.004, 0.12);
      o.connect(gn).connect(this.master!);
      o.start(t + i * 0.03);
      o.stop(t + 0.25);
    });
  }

  release(): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const src = this.noiseSource();
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.Q.value = 1.2;
    bp.frequency.setValueAtTime(380, t);
    bp.frequency.exponentialRampToValueAtTime(1600, t + 0.28);
    const gn = ctx.createGain();
    this.env(gn, t, 0.22, 0.04, 0.3);
    src.connect(bp).connect(gn).connect(this.master!);
    src.start(t);
    src.stop(t + 0.4);
  }

  swish(): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const src = this.noiseSource();
    const hp = ctx.createBiquadFilter();
    hp.type = 'bandpass';
    hp.Q.value = 0.9;
    hp.frequency.setValueAtTime(7200, t);
    hp.frequency.exponentialRampToValueAtTime(2400, t + 0.3);
    const gn = ctx.createGain();
    this.env(gn, t, 0.55, 0.012, 0.34);
    src.connect(hp).connect(gn).connect(this.master!);
    src.start(t);
    src.stop(t + 0.45);
  }

  clang(strength: number): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const base = 430 + Math.random() * 60;
    [1, 2.36, 3.91, 5.4].forEach((ratio, i) => {
      const o = ctx.createOscillator();
      const gn = ctx.createGain();
      o.type = i === 0 ? 'triangle' : 'sine';
      o.frequency.value = base * ratio;
      this.env(gn, t, (0.32 * strength) / (i + 1), 0.002, 0.35 + strength * 0.5 - i * 0.06);
      o.connect(gn).connect(this.master!);
      o.start(t);
      o.stop(t + 1.2);
    });
    const click = this.noiseSource();
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = 2500;
    const cg = ctx.createGain();
    this.env(cg, t, 0.25 * strength, 0.001, 0.04);
    click.connect(hp).connect(cg).connect(this.master!);
    click.start(t);
    click.stop(t + 0.08);
  }

  board(strength: number): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const gn = ctx.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(170, t);
    o.frequency.exponentialRampToValueAtTime(70, t + 0.18);
    this.env(gn, t, 0.6 * strength, 0.003, 0.22);
    o.connect(gn).connect(this.master!);
    o.start(t);
    o.stop(t + 0.3);
    const src = this.noiseSource();
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 900;
    const ng = ctx.createGain();
    this.env(ng, t, 0.3 * strength, 0.002, 0.12);
    src.connect(lp).connect(ng).connect(this.master!);
    src.start(t);
    src.stop(t + 0.2);
  }

  bounce(strength: number): void {
    if (!this.ready || strength < 0.05) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const gn = ctx.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(140, t);
    o.frequency.exponentialRampToValueAtTime(60, t + 0.12);
    this.env(gn, t, 0.5 * Math.min(1, strength), 0.002, 0.14);
    o.connect(gn).connect(this.master!);
    o.start(t);
    o.stop(t + 0.2);
  }

  /** Crowd as shaped noise through vowel-ish formant filters. */
  crowd(kind: 'cheer' | 'roar' | 'ooh' | 'aww'): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const dur = kind === 'roar' ? 2.6 : kind === 'cheer' ? 1.8 : 1.5;
    const peak = kind === 'roar' ? 0.5 : kind === 'cheer' ? 0.32 : 0.26;
    const formants =
      kind === 'ooh' ? [[350, 6], [800, 8]] : kind === 'aww' ? [[700, 6], [1100, 8]] : [[600, 2.5], [1500, 3], [2600, 4]];
    const out = ctx.createGain();
    out.gain.setValueAtTime(0.0001, t);
    out.gain.exponentialRampToValueAtTime(peak, t + (kind === 'ooh' ? 0.35 : 0.12));
    out.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    out.connect(this.master!);
    for (const [freq, q] of formants) {
      const src = this.noiseSource();
      const bp = ctx.createBiquadFilter();
      bp.type = 'bandpass';
      bp.Q.value = q;
      if (kind === 'ooh') {
        bp.frequency.setValueAtTime(freq * 0.85, t);
        bp.frequency.linearRampToValueAtTime(freq * 1.25, t + 0.45);
        bp.frequency.linearRampToValueAtTime(freq * 0.8, t + dur);
      } else if (kind === 'aww') {
        bp.frequency.setValueAtTime(freq, t);
        bp.frequency.exponentialRampToValueAtTime(freq * 0.55, t + dur);
      } else {
        bp.frequency.value = freq;
      }
      const g2 = ctx.createGain();
      g2.gain.value = 1 / formants.length;
      src.connect(bp).connect(g2).connect(out);
      src.start(t, Math.random());
      src.stop(t + dur + 0.1);
    }
    if (kind === 'roar' || kind === 'cheer') {
      for (let i = 0; i < (kind === 'roar' ? 3 : 1); i++) {
        const o = ctx.createOscillator();
        const gw = ctx.createGain();
        const start = t + 0.1 + Math.random() * 0.5;
        o.type = 'sine';
        o.frequency.setValueAtTime(1900 + Math.random() * 400, start);
        o.frequency.linearRampToValueAtTime(2700 + Math.random() * 300, start + 0.18);
        o.frequency.linearRampToValueAtTime(2100, start + 0.32);
        this.env(gw, start, 0.035, 0.03, 0.3);
        o.connect(gw).connect(this.master!);
        o.start(start);
        o.stop(start + 0.4);
      }
    }
  }

  buzzer(): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const lp = ctx.createBiquadFilter();
    const gn = ctx.createGain();
    o.type = 'sawtooth';
    o.frequency.value = 196;
    lp.type = 'lowpass';
    lp.frequency.value = 1400;
    gn.gain.setValueAtTime(0.0001, t);
    gn.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
    gn.gain.setValueAtTime(0.18, t + 0.5);
    gn.gain.exponentialRampToValueAtTime(0.0001, t + 0.7);
    o.connect(lp).connect(gn).connect(this.master!);
    o.start(t);
    o.stop(t + 0.75);
  }

  fanfare(good: boolean): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime + 0.05;
    const notes = good ? [523.25, 659.25, 783.99, 1046.5] : [392, 466.16, 523.25];
    notes.forEach((f, i) => {
      const o = ctx.createOscillator();
      const gn = ctx.createGain();
      o.type = 'triangle';
      o.frequency.value = f;
      this.env(gn, t + i * 0.09, 0.12, 0.01, 0.5);
      o.connect(gn).connect(this.master!);
      o.start(t + i * 0.09);
      o.stop(t + i * 0.09 + 0.6);
    });
  }

  click(): void {
    if (!this.ready) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const gn = ctx.createGain();
    o.type = 'square';
    o.frequency.setValueAtTime(880, t);
    o.frequency.exponentialRampToValueAtTime(440, t + 0.05);
    this.env(gn, t, 0.04, 0.002, 0.06);
    o.connect(gn).connect(this.master!);
    o.start(t);
    o.stop(t + 0.1);
  }

  /** Lift the crowd bed for a moment (slow-mo tension). */
  swell(on: boolean): void {
    if (!this.ambience || !this.ctx) return;
    this.ambience.gain.setTargetAtTime(on ? 0.09 : 0.035, this.ctx.currentTime, on ? 0.15 : 0.6);
  }
}

export const sfx = new Sfx();

export function haptic(pattern: number | number[]): void {
  if ('vibrate' in navigator) {
    try {
      navigator.vibrate(pattern);
    } catch {
      /* unsupported */
    }
  }
}
