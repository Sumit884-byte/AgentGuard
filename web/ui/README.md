# AgentGuard web UI (shadcn/ui)

React + Vite + Tailwind v4 + [shadcn/ui](https://ui.shadcn.com) (Radix, Nova
preset). `web/server.py` serves the committed build in `dist/`, so running the
demo needs only Python. Rebuild after changing anything in `src/`:

```bash
cd web/ui
npm install
npm run build        # writes dist/ (commit it)
npm run dev          # hot reload; start `python web/server.py` first (API proxied to :8000)
```

| File | What |
|---|---|
| `src/App.tsx` | Page layout: scenario and voice pickers, voice orb, composer, story progress |
| `src/components/agent-panel.tsx` | One agent's column: messages, receipts, given-away and blocked counters |
| `src/components/receipt-card.tsx` | Decision receipt: status, call, rule and reason, safe alternative, collapsible checks |
| `src/components/voice-orb.tsx` | Tap-to-talk ring (browser speech recognition) |
| `src/lib/api.ts` | Types and calls for `/api/scenarios`, `/api/session`, `/api/chat` |
| `src/components/ui/` | shadcn components, added with `npx shadcn@latest add` |

`data-testid` attributes are used by `demo/record_demo.py`; keep them when
editing.
