import type { RoundSummary, ShotRecord } from '../game/game';
import type { ExperimentClient } from '../flagsmith/client';
import type { MissFeedbackVariant } from '../flagsmith/flags';
import { rankFor } from './rank';

const ICON_SOUND_ON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>`;
const ICON_SOUND_OFF = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/></svg>`;
const ICON_XRAY = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/></svg>`;

const $ = <T extends HTMLElement = HTMLElement>(root: ParentNode, sel: string) => root.querySelector<T>(sel)!;

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

export interface UiHandlers {
  onPlay(): void;
  onPlayAgain(): void;
  onShare(): void;
  onMuteToggle(): boolean;
}

export class Ui {
  readonly stage: HTMLDivElement;
  readonly canvas: HTMLCanvasElement;
  private hud: HTMLElement;
  private pips: HTMLElement;
  private score: HTMLElement;
  private fire: HTMLElement;
  private hintEl: HTMLElement;
  private callout: HTMLElement;
  private title: HTMLElement;
  private results: HTMLElement;
  private share: HTMLElement;
  private xray: HTMLElement;
  private toastEl: HTMLElement;
  private toastTimer = 0;
  private shareUrl: string | null = null;

  constructor(root: HTMLElement, handlers: UiHandlers, muted: boolean) {
    root.innerHTML = `
      <div class="stage">
        <canvas aria-label="Basketball court"></canvas>
        <div class="ui">
          <header class="hud" aria-live="polite">
            <div class="pips"></div>
            <div class="score-box"><div class="score-label">SCORE</div><div class="score">0</div></div>
            <div class="hud-right"></div>
          </header>
          <div class="hud-buttons interactive" style="position:absolute;top:calc(var(--safe-top) + 14px);right:14px;display:flex;gap:8px">
            <button class="icon-btn xray-btn" aria-label="Flag X-Ray" title="Flag X-Ray (X)" hidden>${ICON_XRAY}</button>
            <button class="icon-btn mute-btn" aria-label="Toggle sound">${muted ? ICON_SOUND_OFF : ICON_SOUND_ON}</button>
          </div>
          <div class="chip fire-chip">ON FIRE</div>
          <div class="hint"></div>
          <div class="callout" aria-live="assertive"></div>

          <section class="screen title-screen visible">
            <h1 class="logo"><span class="brick">BRICK</span><span class="or">OR</span><span class="swish">SWISH</span></h1>
            <div class="title-bottom">
              <p class="tagline">Five free throws. One button. No excuses.</p>
              <span class="chip best-chip" hidden></span>
              <button class="btn btn-primary pulse play-btn">TAP TO PLAY</button>
              <div class="howto"><span><b>Hold</b> anywhere</span><span><b>Release</b> in the green</span></div>
            </div>
          </section>

          <section class="screen results-screen" aria-live="polite">
            <div class="card interactive">
              <div class="kicker"></div>
              <div class="final-score"></div>
              <div class="rank"></div>
              <div class="shot-row"></div>
              <div class="stats"></div>
              <div class="actions">
                <button class="btn btn-primary pulse again-btn">PLAY AGAIN</button>
                <button class="btn btn-secondary share-btn">SHARE SCORE CARD</button>
              </div>
            </div>
          </section>

          <section class="screen share-screen interactive">
            <img class="share-preview" alt="Your Brick or Swish score card" />
            <div class="share-actions">
              <button class="btn btn-primary wide native-share">SHARE</button>
              <a class="btn btn-whatsapp wa-share" target="_blank" rel="noopener" style="display:grid;place-items:center;text-decoration:none">WHATSAPP</a>
              <button class="btn btn-secondary save-btn">SAVE IMAGE</button>
            </div>
            <button class="link-btn close-share">CLOSE</button>
          </section>

          <aside class="xray interactive" aria-label="Flag X-Ray"></aside>
          <div class="toast"></div>
        </div>
      </div>`;

    this.stage = $(root, '.stage');
    this.canvas = $(root, 'canvas');
    this.hud = $(root, '.hud');
    this.pips = $(root, '.pips');
    this.score = $(root, '.score');
    this.fire = $(root, '.fire-chip');
    this.hintEl = $(root, '.hint');
    this.callout = $(root, '.callout');
    this.title = $(root, '.title-screen');
    this.results = $(root, '.results-screen');
    this.share = $(root, '.share-screen');
    this.xray = $(root, '.xray');
    this.toastEl = $(root, '.toast');

    $(root, '.play-btn').addEventListener('click', () => handlers.onPlay());
    $(root, '.again-btn').addEventListener('click', () => handlers.onPlayAgain());
    $(root, '.share-btn').addEventListener('click', () => handlers.onShare());
    $(root, '.close-share').addEventListener('click', () => this.closeShare());
    const mute = $(root, '.mute-btn');
    mute.addEventListener('click', () => {
      mute.innerHTML = handlers.onMuteToggle() ? ICON_SOUND_OFF : ICON_SOUND_ON;
    });
    $(root, '.xray-btn').addEventListener('click', () => this.toggleXray());
  }

  /** True when a pointer event started on an interactive overlay (buttons, cards, panels). */
  isUiTarget(target: EventTarget | null): boolean {
    return target instanceof Element && !!target.closest('button, a, .interactive');
  }

  showTitle(best: number): void {
    const chip = $(this.title, '.best-chip');
    if (best > 0) {
      chip.hidden = false;
      chip.textContent = `BEST ${best}/15`;
    }
    this.title.classList.add('visible');
  }

  startRound(shots: number): void {
    this.title.classList.remove('visible');
    this.results.classList.remove('visible');
    this.share.classList.remove('visible');
    this.hud.classList.add('visible');
    this.pips.innerHTML = Array.from({ length: shots }, (_, i) => `<div class="pip${i === 0 ? ' current' : ''}"></div>`).join('');
    this.setScore(0, false);
    this.setFire(false);
    this.clearCallout();
  }

  setScore(score: number, bump: boolean): void {
    this.score.textContent = String(score);
    if (bump) {
      this.score.classList.remove('bump');
      void this.score.offsetWidth;
      this.score.classList.add('bump');
    }
  }

  markShot(shot: ShotRecord): void {
    const pips = this.pips.children;
    const pip = pips[shot.index] as HTMLElement | undefined;
    if (pip) {
      pip.classList.remove('current');
      pip.classList.add(shot.outcome === 'swish' ? 'swish' : shot.outcome === 'make' ? 'make' : 'miss');
    }
  }

  setCurrent(index: number): void {
    const pip = this.pips.children[index] as HTMLElement | undefined;
    pip?.classList.add('current');
  }

  setFire(on: boolean): void {
    this.fire.classList.toggle('visible', on);
  }

  hint(kind: 'hold' | 'tap-again' | 'none'): void {
    if (kind === 'none') {
      this.hintEl.classList.remove('visible');
      return;
    }
    this.hintEl.innerHTML = kind === 'hold' ? 'HOLD · RELEASE IN THE <b>GREEN</b>' : 'TAP AGAIN TO <b>SHOOT</b>';
    this.hintEl.classList.add('visible');
  }

  showMake(shot: ShotRecord, streak: number): void {
    const swish = shot.outcome === 'swish';
    const word = swish ? (streak >= 3 ? 'SPLASH!' : 'SWISH!') : 'BUCKET!';
    this.callout.innerHTML = `
      <div class="stamp ${swish ? 'swish' : 'make'}">${word}</div>
      <div class="points">+${shot.points}</div>`;
  }

  /** The only UI that differs between experiment arms. */
  showMiss(shot: ShotRecord, variant: MissFeedbackVariant): void {
    if (variant === 'control') {
      const word = shot.outcome === 'rimout' ? 'MISS' : 'BRICK';
      this.callout.innerHTML = `<div class="stamp miss">${word}</div>`;
      return;
    }
    const abs = Math.abs(shot.error);
    const dir = shot.error < 0 ? 'EARLY' : 'LATE';
    const headline = shot.outcome === 'rimout' ? 'SO CLOSE!' : abs <= 0.2 ? 'ALMOST!' : 'NEARLY THERE';
    const pos = Math.max(3, Math.min(97, 50 + (shot.error / 0.25) * 50));
    this.callout.innerHTML = `
      <div class="stamp near">${headline}</div>
      <div class="timing-pill">${abs.toFixed(2)}s ${dir.toLowerCase()}</div>
      <div class="timing-strip">
        <div class="strip-track"><div class="strip-perfect"></div><div class="strip-marker" style="left:50%"></div></div>
        <div class="strip-labels"><span>EARLY</span><span>PERFECT</span><span>LATE</span></div>
      </div>
      <div class="ghost-note"><span class="ghost-dot"></span>Ghost ball = the perfect release</div>`;
    requestAnimationFrame(() => {
      const marker = this.callout.querySelector<HTMLElement>('.strip-marker');
      if (marker) marker.style.left = `${pos}%`;
    });
  }

  clearCallout(): void {
    this.callout.innerHTML = '';
  }

  showResults(summary: RoundSummary, best: number, newBest: boolean): void {
    this.hud.classList.remove('visible');
    this.hint('none');
    this.clearCallout();
    $(this.results, '.kicker').textContent = `ROUND ${summary.round} · FINAL`;
    $(this.results, '.final-score').innerHTML = `${summary.score}<small>/${summary.maxScore}</small>`;
    $(this.results, '.rank').textContent = rankFor(summary.score, summary.maxScore);
    $(this.results, '.shot-row').innerHTML = summary.shots
      .map((s, i) => {
        const cls = s.outcome === 'swish' ? 'swish' : s.outcome === 'make' ? 'make' : 'miss';
        const label = s.outcome === 'swish' ? '+3' : s.outcome === 'make' ? '+2' : 'X';
        return `<div class="shot-chip ${cls}" style="animation-delay:${0.15 + i * 0.07}s">${label}</div>`;
      })
      .join('');
    const swishes = summary.shots.filter((s) => s.outcome === 'swish').length;
    const makes = summary.shots.filter((s) => s.outcome === 'swish' || s.outcome === 'make').length;
    $(this.results, '.stats').innerHTML = `
      <div><b>${makes}/${summary.shots.length}</b>MAKES</div>
      <div><b>${swishes}</b>SWISHES</div>
      <div><b class="${newBest ? 'new-best' : ''}">${best}</b>${newBest ? 'NEW BEST' : 'BEST'}</div>`;
    this.results.classList.add('visible');
  }

  openShare(blob: Blob, text: string, canNativeShare: boolean, handlers: { native(): void; save(): void }): void {
    if (this.shareUrl) URL.revokeObjectURL(this.shareUrl);
    this.shareUrl = URL.createObjectURL(blob);
    $<HTMLImageElement>(this.share, '.share-preview').src = this.shareUrl;
    $<HTMLAnchorElement>(this.share, '.wa-share').href = `https://wa.me/?text=${encodeURIComponent(text)}`;
    const native = $(this.share, '.native-share');
    native.style.display = canNativeShare ? '' : 'none';
    native.onclick = () => handlers.native();
    $(this.share, '.save-btn').onclick = () => handlers.save();
    this.share.classList.add('visible');
  }

  closeShare(): void {
    this.share.classList.remove('visible');
  }

  toast(message: string): void {
    this.toastEl.textContent = message;
    this.toastEl.classList.add('visible');
    clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => this.toastEl.classList.remove('visible'), 2200);
  }

  toggleXray(force?: boolean): void {
    const visible = this.xray.classList.toggle('visible', force);
    if (visible) this.stage.querySelector<HTMLElement>('.xray-btn')!.hidden = false;
  }

  renderXray(client: ExperimentClient, onReset: () => void): void {
    const a = client.currentAssignment;
    const statusClass = client.status === 'ready' ? 'ok' : 'warn';
    const id = client.visitorId.length > 22 ? `${client.visitorId.slice(0, 13)}…${client.visitorId.slice(-6)}` : client.visitorId;
    const row = (k: string, v: string, cls = '') => `<div class="row"><span>${k}</span><span class="${cls}">${v}</span></div>`;
    this.xray.innerHTML = `
      <h4><span>FLAG X-RAY</span><span class="${statusClass}">${client.status.toUpperCase()}</span></h4>
      ${row('identity', escapeHtml(id))}
      ${row('miss_feedback', a ? escapeHtml(`${a.variant} · ${a.source}`) : 'not evaluated yet (first miss)', a?.inExperiment ? 'ok' : '')}
      ${a?.experimentName ? row('experiment', escapeHtml(a.experimentName), 'ok') : ''}
      ${row('aa_sanity_check', escapeHtml(client.aaAssignment ?? '—'))}
      <div class="log">${client.log
        .slice(0, 12)
        .map((l) => `<div class="${l.kind}" title="${escapeHtml(l.message)}">${new Date(l.at).toLocaleTimeString([], { hour12: false })} ${escapeHtml(l.message)}</div>`)
        .join('')}</div>
      <div class="xray-actions"><button class="xr-flush">Flush events</button><button class="xr-reset">New identity</button></div>`;
    this.xray.querySelector('.xr-flush')?.addEventListener('click', () => void client.flush('manual'));
    this.xray.querySelector('.xr-reset')?.addEventListener('click', onReset);
  }
}
