# Product feedback and friction log: Person B (agent and experience)

Input for the Devpost "product feedback", "feature requests" and "friction
log" fields (C8). Every entry below happened while building this project.
Items we did not get to use are listed as such at the end, so nothing here
needs to be taken on trust.

## Gemini API (google-genai Python SDK)

| What happened | Impact | Workaround | Feature request |
|---|---|---|---|
| `gemini-3.8-flash` returned `503 UNAVAILABLE` ("This model is currently experiencing high demand") on every attempt during one session, including 5 retries spread over about 77 seconds. | The live test could not get past the first customer message on that model. | Switched the test to `gemini-3.6-flash`, which passed (both modes, about 2.5 minutes). Model is configurable with `AGENTGUARD_GEMINI_MODEL`. | Publish current capacity per model, or return a `retry-after` hint with the 503. |
| One request dropped with `RemoteProtocolError: Server disconnected without sending a response`, and our first live run took 11 minutes before failing. | A single stuck call blocked the whole scenario. | Added our own retry with backoff for 5xx, 429 and dropped connections, and a 120-second request timeout. 400 errors are never retried. | Retries for 503/429 and a finite request timeout on by default in the SDK. |
| Function calling on Gemini 3 needs each model turn's thought signatures sent back unchanged. Our agent keeps history in a provider-neutral format, so rebuilding the parts would have dropped them. | Easy to get wrong silently. | Keep the original response `Part` objects and replay them as-is. | A warning when a function-calling turn is replayed without its signature. |
| `parameters_json_schema` accepted our strict JSON schemas (`additionalProperties: false`, `required`) unchanged. | Positive: the same tool definitions work for both providers. | None needed. | None. |

## Browser speech APIs (Alexa+ web page)

| What happened | Impact | Workaround | Feature request |
|---|---|---|---|
| Speech recognition is only available as the prefixed `webkitSpeechRecognition` (Chrome, Edge), not in Firefox. | Voice input cannot be the only way in. | The page falls back to a text box and says when voice is unsupported. | A standard, unprefixed `SpeechRecognition` across browsers. |
| Speech synthesis reads markdown literally: a reply containing `**$23.99/month**` would be spoken with the asterisks. | Model replies often use light markdown. | Strip markdown before speaking; render bold in the chat bubble. | None (expected behaviour), but worth knowing. |
| Voice input has not yet been checked with a real microphone; only the text path and spoken replies were exercised. | Demo risk. | Manual check in Chrome before recording. | None. |

## Agent behaviour we observed (live Gemini runs, test backend)

These are findings about LLM agents, useful for the "what we learned" text.
They came from runs against the in-memory test backend, not the final
policy server, so they are observations, not results.

- When the guardrail blocked an 80% discount, the guarded agent retried
  with 50%, 30% and 25% before accepting the 20% cap. Guardrails must hold
  against limit probing, not just the first request.
- In one run the guarded agent, after its discount was blocked, issued a
  $15 "goodwill" refund instead. Blocking one benefit can push the agent to
  substitute another, so refund rules need to stand on their own.
- The guarded agent applied the suggested safe alternative (20% off)
  without asking the customer first. The Agent Skill now tells the agent to
  offer it and wait; the system prompt does not yet.

## Development friction

| What happened | Impact | What we changed |
|---|---|---|
| A real Gemini key was pasted into `.env.example` and committed. | The key is in git history on every branch and has to be revoked. | `.env.example` blanked with a "never put real keys here" warning. Follow-up: add a secret scan before commit. |
| The GitHub CLI's stored token went invalid without warning. | Pull requests could not be opened from the terminal. | Opened PRs from pre-filled compare links in the browser. |

## Not used yet (fill in after first use)

- **Amazon Bedrock:** the provider is written (via the Anthropic SDK's
  Bedrock client) and tested offline, but no live call has been made: no
  AWS credentials were available yet. Model access also has to be enabled
  per account and region in the Bedrock console before the first call.
- **Strands Agents:** not used. Cut per the plan's cut list (B3 stands in
  for B2) because there were no AWS credentials and no HTTP MCP server yet.
- **MCP Python SDK:** the agent calls the backend in-process (contract v2,
  phase 1), so Person B has not used the MCP client side. Person A's server
  notes (A8) cover the SDK.
