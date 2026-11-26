import type { RoundSummary } from '../game/game';
import { rankFor } from './rank';

const W = 1080;
const H = 1350;

function chipColor(outcome: string): string {
  if (outcome === 'swish') return '#3dfcff';
  if (outcome === 'make') return '#4dff9a';
  return '#ff3b5c';
}

/** Renders the 4:5 share card (Instagram/WhatsApp friendly) to a PNG blob. */
export async function renderScoreCard(summary: RoundSummary, url: string): Promise<Blob> {
  await document.fonts?.ready;
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const ctx = c.getContext('2d')!;

  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, '#04020d');
  bg.addColorStop(0.55, '#1c0a3e');
  bg.addColorStop(1, '#3a0d52');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Stars
  for (let i = 0; i < 160; i++) {
    ctx.fillStyle = `rgba(255,255,255,${0.2 + Math.random() * 0.6})`;
    ctx.beginPath();
    ctx.arc(Math.random() * W, Math.random() * H * 0.6, Math.random() * 1.8, 0, Math.PI * 2);
    ctx.fill();
  }

  // Sun
  const horizon = H * 0.86;
  const sunR = 220;
  const halo = ctx.createRadialGradient(W / 2, horizon, 100, W / 2, horizon, 700);
  halo.addColorStop(0, 'rgba(255,43,214,0.5)');
  halo.addColorStop(1, 'rgba(255,43,214,0)');
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, W, H);
  const sun = ctx.createLinearGradient(0, horizon - sunR, 0, horizon);
  sun.addColorStop(0, '#fff3a1');
  sun.addColorStop(0.5, '#ff9a4d');
  sun.addColorStop(1, '#ff2bd6');
  ctx.save();
  ctx.beginPath();
  ctx.arc(W / 2, horizon, sunR, Math.PI, 0);
  ctx.clip();
  ctx.fillStyle = sun;
  ctx.fillRect(0, horizon - sunR, W, sunR);
  ctx.globalCompositeOperation = 'destination-out';
  for (let i = 0; i < 7; i++) ctx.fillRect(0, horizon - sunR * 0.5 + i * 24, W, 4 + i * 2.5);
  ctx.restore();

  // Grid floor
  ctx.fillStyle = '#0c0420';
  ctx.fillRect(0, horizon, W, H - horizon);
  ctx.strokeStyle = 'rgba(255,43,214,0.55)';
  ctx.lineWidth = 2;
  for (let i = -12; i <= 12; i++) {
    ctx.beginPath();
    ctx.moveTo(W / 2 + i * 18, horizon);
    ctx.lineTo(W / 2 + i * 220, H);
    ctx.stroke();
  }
  for (let i = 1; i < 9; i++) {
    const y = horizon + Math.pow(i / 8, 2) * (H - horizon);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
  ctx.fillStyle = 'rgba(255,140,230,0.9)';
  ctx.fillRect(0, horizon - 2, W, 3);

  const neon = (text: string, x: number, y: number, size: number, color: string, glow: string, font = 'Bebas Neue') => {
    ctx.font = `${size}px "${font}", Impact, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    for (const blur of [60, 26, 8]) {
      ctx.shadowColor = glow;
      ctx.shadowBlur = blur;
      ctx.fillStyle = color;
      ctx.fillText(text, x, y);
    }
    ctx.shadowBlur = 0;
  };

  neon('BRICK', W / 2 - 170, 190, 150, '#ffe6d6', '#ff7a1a');
  ctx.font = '700 34px "Space Grotesk", sans-serif';
  ctx.fillStyle = 'rgba(245,247,255,0.7)';
  ctx.textAlign = 'center';
  ctx.fillText('OR', W / 2 + 10, 168);
  neon('SWISH', W / 2 + 190, 190, 150, '#e3ffff', '#3dfcff');

  ctx.font = '600 34px "Space Grotesk", sans-serif';
  ctx.fillStyle = 'rgba(245,247,255,0.6)';
  ctx.fillText(`ROUND ${summary.round} · ${summary.shots.length} SHOTS`, W / 2, 272);

  const scoreText = String(summary.score);
  const maxText = `/${summary.maxScore}`;
  ctx.font = '340px "Bebas Neue", Impact, sans-serif';
  const scoreW = ctx.measureText(scoreText).width;
  ctx.font = '120px "Bebas Neue", Impact, sans-serif';
  const maxW = ctx.measureText(maxText).width;
  const left = W / 2 - (scoreW + 16 + maxW) / 2;
  neon(scoreText, left + scoreW / 2, 595, 340, '#ffffff', '#3dfcff');
  ctx.font = '120px "Bebas Neue", Impact, sans-serif';
  ctx.fillStyle = 'rgba(245,247,255,0.5)';
  ctx.textAlign = 'left';
  ctx.fillText(maxText, left + scoreW + 16, 595);
  ctx.textAlign = 'center';

  const rank = rankFor(summary.score, summary.maxScore);
  neon(rank, W / 2, 705, 100, '#ffd23f', '#ff2bd6');

  // Shot chips
  const size = 110;
  const gap = 26;
  const total = summary.shots.length * size + (summary.shots.length - 1) * gap;
  summary.shots.forEach((s, i) => {
    const x = W / 2 - total / 2 + i * (size + gap);
    const y = 752;
    const col = chipColor(s.outcome);
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    ctx.strokeStyle = col;
    ctx.lineWidth = 4;
    ctx.shadowColor = col;
    ctx.shadowBlur = 24;
    ctx.beginPath();
    ctx.roundRect(x, y, size, size, 28);
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = col;
    ctx.font = '60px "Bebas Neue", Impact, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(s.outcome === 'swish' ? '+3' : s.outcome === 'make' ? '+2' : 'X', x + size / 2, y + size / 2 + 22);
  });

  ctx.font = '700 46px "Space Grotesk", sans-serif';
  ctx.fillStyle = '#ffffff';
  ctx.fillText('Think you can beat that?', W / 2, H - 118);
  ctx.font = '600 34px "Space Grotesk", sans-serif';
  ctx.fillStyle = '#3dfcff';
  ctx.fillText(url.replace(/^https?:\/\//, '').replace(/\/$/, ''), W / 2, H - 62);

  return new Promise((resolve, reject) =>
    c.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png'),
  );
}

export function shareText(summary: RoundSummary, url: string): string {
  return `I scored ${summary.score}/${summary.maxScore} in Brick or Swish (${rankFor(summary.score, summary.maxScore)}). Think you can beat that? ${url}`;
}

export async function shareCard(blob: Blob, text: string): Promise<'shared' | 'unsupported' | 'cancelled'> {
  const file = new File([blob], 'brick-or-swish.png', { type: 'image/png' });
  try {
    if (navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], text, title: 'Brick or Swish' });
      return 'shared';
    }
    if (navigator.share) {
      await navigator.share({ text, title: 'Brick or Swish' });
      return 'shared';
    }
  } catch (err) {
    if ((err as DOMException)?.name === 'AbortError') return 'cancelled';
  }
  return 'unsupported';
}

export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
