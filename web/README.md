# Simulated Alexa+ demo (B5)

One customer talks to two billing agents at once: the **naive** agent (no
guardrails) and the **guarded** agent (AgentGuard policies). Each reply shows
the decision receipt of every tool call as a card underneath.

- Voice in: tap the ring and speak (browser speech recognition; works in
  Chrome and Edge). Typing works everywhere.
- Voice out: replies are spoken with the browser's speech synthesis. Choose
  both agents, one, or off.
- "Use next line from this story" plays the selected scenario's next scripted
  attack line, so a demo can follow S1 to S8 exactly.

## Run

From the repo root, with a provider configured in `.env` (see `.env.example`):

```bash
python web/server.py                     # Person A's make_backend: real policies
open http://localhost:8000
```

Until `agentguard.integration.backend:make_backend` lands, you can try the page
with the test stand-in. It enforces only a few rules and fills no money
fields, so never record a demo or quote numbers from it:

```bash
python web/server.py --backend tests.fakes:backend_factory
```

Options: `--port`, `--backend module:function`. The model comes from
`default_llm()` (`AGENTGUARD_PROVIDER`, `AGENTGUARD_*_MODEL`).

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/scenarios` | | scenarios, model, backend |
| POST | `/api/session` | `{"scenario_id": "S1"}` | `session_id`, scenario |
| POST | `/api/chat` | `{"session_id", "message"}` | per mode: `text`, `status`, `calls` (with `receipt`), `state` |

Both agents run in parallel for each message, using the simulator's agent
loop, prompt and tools.
