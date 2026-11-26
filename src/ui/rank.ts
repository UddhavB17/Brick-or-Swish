export function rankFor(score: number, max: number): string {
  const r = score / max;
  if (score === max) return 'PERFECT GAME';
  if (r >= 0.8) return 'SPLASH ARTIST';
  if (r >= 0.6) return 'BUCKET GETTER';
  if (r >= 0.4) return 'ROLE PLAYER';
  if (r >= 0.2) return 'BENCH WARMER';
  return 'BRICK LAYER';
}
