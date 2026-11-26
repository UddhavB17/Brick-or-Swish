# HANDOFF — Brick or Swish

Living handoff doc. Update at every milestone so any model/person can continue.

## Status
- [x] Scaffold: Vite + TypeScript (vanilla, no framework), `.env.example`, `vercel.json`
- [ ] Flagsmith client (identity, exposure, events, flush)
- [ ] Game (canvas renderer, physics, meter, audio, UI)
- [ ] HYPOTHESIS.md, docs/flagsmith-setup.md, sim script, README
- [ ] Screenshots + PR

## Next steps
1. Write `src/flagsmith/client.ts` and `src/flagsmith/telemetry.ts`.
2. Build the game under `src/game/`, `src/audio/`, `src/ui/`.
3. Docs + sim script, screenshots, PR.

## Commands
```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc + vite build -> dist/
```

## Repo rules
- Commits authored as `UddhavB17 <200227057+UddhavB17@users.noreply.github.com>`, no co-author trailers.
- Never commit `.env` or real keys.
