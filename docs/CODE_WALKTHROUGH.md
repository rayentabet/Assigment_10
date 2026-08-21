# Code walkthrough

## Boundaries

The project has four application boundaries under `services/`:

```text
frontend -> Agent A -> System B
                    -> MCP -> Qdrant
```

- The frontend calls only Agent A's public FastAPI API.
- Agent A owns conversation state, LangGraph routing, approvals and payments.
- System B owns DigiKey discovery, OAuth and sandbox ordering.
- The MCP service owns the embedded robotics RAG runtime and corpus assets.
- Agent A communicates with System B over A2A instead of importing its code.

## Frontend

`services/frontend/src/App.tsx` composes the conversation sidebar, chat panel
and activity panel. `src/hooks/useConversation.ts` owns the active thread,
history, streaming messages, approvals and current tool activity.

`src/api/client.ts` is the only HTTP client. It calls Agent A at the configured
`VITE_API_BASE_URL`. `src/api/types.ts` mirrors the public Pydantic schemas in
Agent A and must contain only public response fields.

Voice input records a browser `MediaRecorder` blob and posts it to Agent A's
`/threads/{id}/transcribe` route. Transcribed text is placed in the input; it
does not enter LangGraph until the user sends it.

## Agent System A

Agent A lives in `services/agent-system-a/`.

### API and conversation service

`app/api/main.py` exposes thread, message, streaming, approval, transcription,
DigiKey OAuth proxy and payment-method routes. Request and response models live
in `app/api/schemas.py`.

`app/chat_service.py` persists public history and LangGraph checkpoints in
SQLite. It is the boundary between HTTP requests and graph execution.

### LangGraph

`app/graph.py` defines the supervisor graph and model-visible `AgentState`.
Specialists live in `agents/`:

- `rag_agent.py`: grounded robotics questions through MCP;
- `coding_agent.py`: restricted Arduino/Python generation;
- `wiring_agent.py`: deterministic pin planning and validation;
- `robot_visualization_agent.py`: structured robot previews.

Inventory, prices and purchases route to the A2A component client under
`app/integrations/`, which contacts System B.

`app/guardrails.py` validates input and sanitizes final model output. Tool
results remain structured internally; only approved public fields are returned
to React.

### Generated artifacts

Tool implementations live in `tools/`. Generated code and robot models are
written beneath the configured generated directory. Git retains placeholders
and selected examples while ignoring runtime artifacts.

### Transcription

`app/transcription.py` lazily loads `faster-whisper` and performs blocking
decoding in a worker thread. Model weights are downloaded on first use inside
the current environment or container.

## Credential and payment flow

`app/payment_vault.py` defines the generic `CredentialProvider` boundary and
the Lithic Sandbox implementation. `app/payment_service.py` is deterministic
and is the only layer allowed to resolve a local `payment_method_id` to
provider-sensitive material.

The model-visible representation contains only:

```json
{
  "payment_method_id": "pm_...",
  "display": "Virtual Visa ending 4242"
}
```

It never contains PAN, CVV, expiry, Lithic API keys, provider tokens or raw
provider responses. Provider errors are converted to sanitized messages before
they reach public history or logs.

The purchase sequence is:

```text
proposal -> AP2 user approval -> mandate validation -> PaymentService
         -> Lithic Sandbox authorization -> DigiKey sandbox ordering
```

Mandate validation covers user, merchant, amount, items, expiry, nonce and
single use. Approval must occur before payment execution. See
`docs/LITHIC_PAYMENT.md` for limitations and security details.

## Agent System B

System B lives in `services/agent-system-b/component_manager/`.

- `agent.py`: Google ADK agent definition;
- `server.py`: A2A application on port 8002;
- `rest_api.py`: REST/SSE surface and Agent A's OAuth proxy target on 8003;
- `digikey.py`: Product Information API client and offer ranking;
- `oauth.py`: DigiKey three-legged OAuth with Fernet-encrypted tokens;
- `purchasing.py`: deterministic proposal and sandbox-order logic;
- `db.py`: persistent component, proposal, mandate and OAuth data;
- `tools.py`: deterministic tool boundary exposed to ADK.

System B serves A2A and REST concurrently from one Docker container. Its
persistent data is mounted at `/app/component_manager/data`.

## MCP server

`services/mcp-server/mcp_server/server.py` exposes the embedded `rag/` package
through Streamable HTTP. It provides document search, grounded answers, image
lookup and corpus metadata. Agent A authenticates with `MCP_AUTH_TOKEN` and
connects at `http://mcp-server:8000/mcp` inside Compose.

`mcp_server/qdrant_bootstrap.py` checks the collection before MCP starts. A
fresh Qdrant volume is restored from the bundled snapshot; an existing volume
is left unchanged. Qdrant remains a separate service and persistent volume.

## Tests and evaluation

`tests/` covers APIs, graph routing, guardrails, payment isolation,
transcription, MCP integration and isolated System B behavior. Run it with:

```bash
source .venv/bin/activate
pytest
```

`evaluation/` is independent of the test suite. Golden datasets live under
`evaluation/golden_dataset/`; every saved run under `evaluation/runs/` is kept
for comparison in the Streamlit dashboard.

## Recommended reading order

1. `services/agent-system-a/app/api/schemas.py`
2. `services/agent-system-a/app/api/main.py`
3. `services/agent-system-a/app/chat_service.py`
4. `services/agent-system-a/app/graph.py`
5. `services/agent-system-a/app/payment_service.py`
6. `services/agent-system-a/app/payment_vault.py`
7. `services/agent-system-b/component_manager/agent.py`
8. `services/agent-system-b/component_manager/purchasing.py`
9. `services/frontend/src/hooks/useConversation.ts`
10. `services/frontend/src/api/client.ts`
