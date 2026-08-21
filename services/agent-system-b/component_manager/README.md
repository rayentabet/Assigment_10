# Component Manager (System B)

System B is an independent Google ADK agent. System A reaches it through A2A;
it does not import System B or read its SQLite database.

Its four tools are:

- `search_digikey`: search and rank real DigiKey Product Information V4 offers.
- `create_digikey_proposal`: refresh an offer and create signed AP2 proposal evidence.
- `place_digikey_order`: after human approval, submit exactly once to DigiKey Sandbox.
- `get_digikey_order`: read the locally recorded sandbox order reference.

Search uses two-legged OAuth. Ordering uses a separate three-legged OAuth
connection. Access and refresh tokens are encrypted in System B's SQLite
database. AP2 and approval signing keys are generated locally in ignored files.
Production ordering is disabled in code.

The React purchase approval uses AP2 together with Agent A's deterministic
Payment Service. Lithic card details and provider references remain inside the
credential provider and never reach this ADK agent or an LLM. System B receives
only the AP2-approved purchase evidence required for its sandbox ordering flow.
DigiKey Sandbox ordering still uses the OAuth-connected DigiKey account.

## Run

From the repository root:

```bash
PYTHONPATH=services/agent-system-b \
  .venv/bin/uvicorn component_manager.server:app --host 0.0.0.0 --port 8002
```

Full setup, architecture, function descriptions, and request flow are documented
in `docs/CODE_WALKTHROUGH.md`.

## Standalone REST + SSE (dev/testing)

`rest_api.py` is a second, additive server for talking to System B directly
over plain HTTP instead of A2A JSON-RPC — useful for manual testing and demos.
It runs alongside `server.py` on its own port and does not change how System A
talks to System B.

```bash
PYTHONPATH=services/agent-system-b \
  .venv/bin/uvicorn component_manager.rest_api:app --host 0.0.0.0 --port 8003
```

Threads are persisted to `component_manager/data/sessions.sqlite`
(`SqliteSessionService`), so a `thread_id` keeps working across restarts:

```bash
# Create a thread
curl -X POST localhost:8003/threads
# => {"thread_id": "..."}

# Send a message, get one JSON reply
curl -X POST localhost:8003/threads/<thread_id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"message": "Search DigiKey for an hc-sr04"}'

# Send a message and stream text/tool-call/tool-result events live
curl -N -X POST localhost:8003/threads/<thread_id>/messages/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "search digikey for hc-sr04 qty 2"}'

# Replay a thread's history (works after a restart too)
curl localhost:8003/threads/<thread_id>/messages
```
