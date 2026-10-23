# Strands agent and billing MCP servers (B2)

A Strands agent that reaches the billing tools only through MCP over
Streamable HTTP, as in contract v2 phase 2. It uses the same system prompt as
the in-process agent; naive vs guarded is just a different server URL.

```bash
pip install -e ".[agent]"
```

## 1. Start the servers

Person A's servers, once they land, run on `:8001` (naive) and `:8002`
(guarded). Until then, the stub in `stub_server.py` serves the same contract
from any `make_backend`-style factory:

```bash
python -m agentguard.strands_agent.stub_server --mode naive     # :8001
python -m agentguard.strands_agent.stub_server --mode guarded   # :8002
# dev only, before make_backend exists (not for recorded numbers):
python -m agentguard.strands_agent.stub_server --mode guarded --backend tests.fakes:backend_factory
```

| Route | What |
|---|---|
| `/mcp` | MCP Streamable HTTP. Requires `Authorization: Bearer demo-<customer_id>`; 401 otherwise. |
| `POST /admin/reset` `{"scenario_id": "S1"}` | Reloads that scenario's seed; returns its customer and demo token. |
| `GET /admin/snapshot` | Current backend state, so runs record initial and final state. **Proposed addition to contract v2.** |

Identity comes from the token, never from tool arguments. A call whose token
does not match the active scenario's customer returns an ERROR receipt.

## 2. Run the agent

```bash
python -m agentguard.strands_agent                                 # Bedrock, all 8 scenarios, both servers
python -m agentguard.strands_agent --provider gemini --scenarios S1 S3
python -m agentguard.strands_agent --skill skills/agentguard-billing   # load the Agent Skill (B6)
python -m agentguard.strands_agent --naive-url http://host:8001/mcp --guarded-url http://host:8002/mcp
```

Writes `runs/<run_id>/<scenario>.<mode>.json`, the same `ScenarioRun` format
as the in-process runner, so the exporter and scoreboard read it unchanged.
Receipts are recorded with the same `apply_receipt` the simulator uses.

Models: `--provider bedrock` (Strands `BedrockModel`; `AWS_REGION`,
`AGENTGUARD_BEDROCK_MODEL`, standard AWS credentials) or `--provider gemini`
(`GEMINI_API_KEY`, `AGENTGUARD_GEMINI_MODEL`).

## What has been verified

- **Live, with Gemini:** Strands agent → MCP over Streamable HTTP with a bearer
  token → stub servers with the test backend. Naive applied 80% off; guarded
  blocked the stacked discount (S1) and every call on another customer's
  account (S3). The Agent Skill loaded through the Strands skills plugin and
  the agent activated it on its own.
- **In CI, no keys needed:** the same loop end to end over HTTP with a scripted
  Strands model (`tests/test_strands_agent.py`).
- **Not verified:** a live Bedrock call. No AWS credentials were available.
  `make_model("bedrock")` is tested only for configuration.

## For Person A

- Under `mcp` 2.x, `from mcp.server.fastmcp import FastMCP` no longer exists
  (renamed to `MCPServer`), so `agentguard/mcp/server.py` fails to import once
  2.x is installed. This is task A1; `stub_server.py` shows the 2.x pattern
  (`MCPServer`, `token_verifier` + `AuthSettings`, `get_access_token()`,
  `custom_route`).
- Demo token format here is `demo-<customer_id>`; contract v2 does not fix one.
  Please confirm or change it, and consider adding `GET /admin/snapshot`.
