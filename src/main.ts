import './styles.css';
import { sfx } from './audio/sfx';
import { config } from './config';
import { experiments } from './flagsmith/client';
import { Telemetry } from './flagsmith/telemetry';
import { Game, type RoundSummary } from './game/game';
import { downloadBlob, renderScoreCard, shareCard, shareText } from './ui/share';
import { Ui } from './ui/ui';

const BEST_KEY = 'bos_best';
const MISS_DWELL = 2.1;
const MAKE_DWELL = 1.15;

const telemetry = new Telemetry(experiments);
let lastSummary: RoundSummary | null = null;
let best = Number(localStorage.getItem(BEST_KEY) ?? 0) || 0;

const ui = new Ui(
  document.querySelector<HTMLDivElement>('#app')!,
  {
    onPlay: () => {
      sfx.unlock();
      sfx.click();
      game.startRound();
    },
    onPlayAgain: () => {
      sfx.click();
      game.startRound();
    },
    onShare: () => void openShare(),
    onMuteToggle: () => {
      sfx.unlock();
      sfx.setMuted(!sfx.muted);
      return sfx.muted;
    },
  },
  sfx.muted,
);

const game = new Game(
  ui.canvas,
  {
    onRoundStart(round) {
      telemetry.roundStarted(round);
      ui.startRound(config.shotsPerRound);
    },
    onShotReleased() {
      telemetry.shotTaken();
    },
    onShotResolved(shot, ctx) {
      ui.markShot(shot);
      if (shot.points > 0) {
        ui.setScore(ctx.score, true);
        ui.setFire(ctx.streak >= 2);
        ui.showMake(shot, ctx.streak);
        return { ghost: false, dwell: MAKE_DWELL };
      }
      ui.setFire(false);
      // Exposure happens here, at the moment the miss screen renders.
      const assignment = experiments.resolveMissFeedback();
      telemetry.missShown();
      ui.showMiss(shot, assignment.variant);
      // Same dwell for both arms so only the content of the miss screen differs.
      return { ghost: assignment.variant === 'near_miss', dwell: MISS_DWELL };
    },
    onFeedbackEnd() {
      ui.clearCallout();
      if (game.phase !== 'over') ui.setCurrent(game.shotIndex + 1);
    },
    onRoundOver(summary) {
      lastSummary = summary;
      const newBest = summary.score > best;
      if (newBest) {
        best = summary.score;
        localStorage.setItem(BEST_KEY, String(best));
      }
      telemetry.roundCompleted(summary.score, summary.round);
      setTimeout(() => ui.showResults(summary, best, newBest), 650);
    },
    onHint(hint) {
      ui.hint(hint);
    },
  },
  config.shotsPerRound,
);

async function openShare(): Promise<void> {
  if (!lastSummary) return;
  sfx.click();
  telemetry.shared();
  const url = `${window.location.origin}/`;
  const text = shareText(lastSummary, url);
  const blob = await renderScoreCard(lastSummary, url);
  const file = new File([blob], 'brick-or-swish.png', { type: 'image/png' });
  const canNative = !!navigator.canShare?.({ files: [file] }) || !!navigator.share;
  ui.openShare(blob, text, canNative, {
    native: async () => {
      const result = await shareCard(blob, text);
      if (result === 'unsupported') {
        downloadBlob(blob, 'brick-or-swish.png');
        ui.toast('Saved. Post it anywhere.');
      }
    },
    save: () => {
      downloadBlob(blob, 'brick-or-swish.png');
      ui.toast('Score card saved');
    },
  });
}

// ------------------------------------------------------------------ input

const stamp = (e: Event) => (e.timeStamp > 0 ? e.timeStamp : performance.now());

ui.stage.addEventListener('pointerdown', (e) => {
  if (ui.isUiTarget(e.target) || game.phase === 'attract' || game.phase === 'over') return;
  e.preventDefault();
  sfx.unlock();
  game.press(stamp(e));
});
window.addEventListener('pointerup', (e) => game.lift(stamp(e)));
window.addEventListener('pointercancel', (e) => game.lift(stamp(e)));

window.addEventListener('keydown', (e) => {
  if (e.code === 'KeyX' && !e.repeat) {
    ui.toggleXray();
    return;
  }
  if (e.code !== 'Space' && e.code !== 'Enter') return;
  e.preventDefault();
  if (e.repeat) return;
  sfx.unlock();
  if (game.phase === 'attract') {
    sfx.click();
    game.startRound();
  } else if (game.phase === 'over') {
    game.startRound();
  } else {
    game.press(stamp(e));
  }
});
window.addEventListener('keyup', (e) => {
  if (e.code === 'Space' || e.code === 'Enter') game.lift(stamp(e));
});

// ------------------------------------------------------------------ layout + boot

const resize = () => game.resize(window.innerWidth, window.innerHeight);
window.addEventListener('resize', resize);
window.visualViewport?.addEventListener('resize', resize);
resize();

const renderXray = () =>
  ui.renderXray(experiments, () => {
    localStorage.removeItem('bos_visitor_id');
    window.location.reload();
  });
experiments.onChange(renderXray);
renderXray();
if (config.debug) ui.toggleXray(true);

ui.showTitle(best);
game.start();
void experiments.start();

if (import.meta.env.DEV) {
  (window as unknown as { __bos: unknown }).__bos = { game, experiments };
}
