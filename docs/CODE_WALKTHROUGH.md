# Code Walkthrough

This guide explains how the application is organized and how one user request moves through the complete system.

## 1. Repository map

```text
Assignment_10/
├── agents/                 LangChain specialist definitions
├── app/
│   ├── api/                FastAPI routes and response schemas
│   ├── helpers/            Reusable parsing and file-validation helpers
│   ├── chat_service.py     Conversation persistence and graph execution
│   ├── config.py           Environment-backed settings
│   ├── graph.py            LangGraph state, nodes, routes, and approvals
│   └── guardrails.py       Input/output safety checks
├── component_manager/      Independent Google ADK System B
├── docs/                   Proposal, diagrams, archive, and this guide
├── evaluation/             Evaluation runner and dashboard
├── mcp_server/             Independent Arduino RAG MCP service
├── tests/                  All Python tests in one hierarchy
│   └── component_manager/  System B tests with an isolated database fixture
├── tools/                  Deterministic tools used by agents or graph nodes
├── web/                    React and TypeScript frontend
└── compose.yaml            Multi-service local deployment
```

The main separation is:

- `web/` displays state but never contacts internal services directly.
- `app/` owns the public API, conversation lifecycle, and LangGraph workflow.
- `agents/` contain prompts, models, and the exact tools available to each local specialist.
- `tools/` contain deterministic operations; models do not implement these rules themselves.
- `mcp_server/` exposes the Assignment 8 RAG over MCP.
- `component_manager/` is a separate Google ADK application reached only through A2A.

## 2. React to FastAPI

The frontend starts at `web/src/main.tsx`, which creates the React application and TanStack Query client. `web/src/App.tsx` composes the sidebar, chat panel, and activity panel.

`web/src/hooks/useConversation.ts` owns the active thread. It loads history, sends a message, resumes approvals, and stores the latest wiring, purchase, image, and tool information. API requests are defined in `web/src/api/client.ts`; React calls only FastAPI.

FastAPI starts in `app/api/main.py`:

- `lifespan()` opens the shared SQLite service at startup and closes it at shutdown.
- `create_thread()` creates a conversation UUID.
- `post_message()` receives a user message and calls `send_message()`.
- `resume_message()` continues a graph paused at an approval node.
- `get_messages()` returns public history and saved artifacts.
- `get_artifact()` serves a validated image through an opaque identifier.
- `chat_response()` converts internal graph state into the stable public response schema.

The request and response models are in `app/api/schemas.py`. They prevent blank messages and ensure React receives predictable fields.

## 3. Conversation persistence

`app/chat_service.py` is the boundary between FastAPI, SQLite, and LangGraph.

- `initialize()` opens SQLite, creates application tables, creates the LangGraph checkpointer, and compiles the graph once.
- `send_message()` creates or reuses a thread, saves the user message, invokes LangGraph, and saves the completed public answer.
- `resume_thread()` resumes the same checkpoint using the user's approval decision.
- `create_thread()`, `list_threads()`, `get_history()`, and `delete_thread()` manage conversations.
- `register_artifacts()` maps validated files to opaque artifact IDs.
- `save_wiring()` and `get_wiring()` persist the latest structured wiring plan.
- `save_purchase()` and `get_purchase()` persist the public order reference.

SQLite has two responsibilities: public chat records and LangGraph checkpoints. The Component Manager owns a different database; System A never reads it directly.

## 4. LangGraph state and execution

`app/graph.py` contains the workflow. `AgentState` is the shared state passed between nodes. Important fields include:

- `thread_id` and `original_query`;
- message, route, and completed-task history;
- specialist results and sanitized tool traces;
- image paths and the structured wiring plan;
- pending purchase proposal and completed purchase reference;
- iteration count and final answer.

`ProjectPlan` groups the board, components, wiring, code artifact, model
artifact, and purchase state. Specialists update this single object rather
than maintaining unrelated output fields.

`build_graph()` registers every node and edge. A normal turn follows this order:

```text
START
  → input_guardrail
  → supervisor
  → selected specialist
  → supervisor (repeat when another task remains)
  → finalizer
  → END
```

The main node functions are:

- `input_guard()` checks and masks the request.
- `supervise()` asks the routing model for a strict `RouteDecision`.
- `route_agent()` applies retry limits and sends file-writing agents through approval.
- `approve_action()` pauses before code generation or 3D model rendering.
- `run_agent()` invokes one local specialist and records its answer, tools, images, and wiring result.
- `run_component()` sends the supervisor task to System B through A2A.
- `approve_purchase()` pauses on the exact price and generates an idempotency key after approval.
- `finalize()` joins completed specialist answers without adding new claims.

The supervisor has no tools. It chooses the next node but cannot search documents, write files, allocate pins, or place orders itself.

## 5. Local specialists

Each file in `agents/` exports a short `build_agent()` factory. `app/graph.py` imports each factory under a descriptive alias.

### RAG Agent

`agents/rag_agent.py` connects to the MCP server and exposes only these remote tools to the production agent:

- `answer_question`
- `show_image`

For documentation questions, the agent must use MCP evidence and return source names and locations. `search_documents` remains on the MCP server for evaluation and debugging but is filtered out of the production agent tool list.

### Coding Agent

`agents/coding_agent.py` receives:

- `save_code`
- `validate_code`

Their implementation is in `tools/code_tools.py`. `code_path()` prevents directory traversal, `save_code()` writes the approved file, and `validate_code()` checks it. Generated code is not automatically executed.

### Wiring Agent

`agents/wiring_agent.py` receives the public wiring tools from `tools/wiring_tools.py`. Board and component definitions are loaded from `tools/data/components.json`.

The model interprets the request, but `allocate_pins()` and `validate_wiring()` enforce the real rules. The final structured plan is extracted by `app.helpers.extract_result()` and saved in graph state. When coding or visualization runs later, `run_agent()` adds the confirmed wiring plan to its prompt so every output uses the same pins.

### Visualization Agent

`agents/robot_visualization_agent.py` receives:

- `save_model`
- `render_model`
- `render_model_image`

`tools/model_tools.py` restricts model names and paths, validates each part against a shape schema, builds the geometry with build123d, and returns a preview artifact — `render_model` writes a scalable `preview.svg` and `render_model_image` draws the same isometric projection into a raster `preview.png`. Neither uses an external binary nor executes model-provided code.

## 6. Helper modules

Helpers live in `app/helpers/` so workflow code is not mixed with parsing details.

`messages.py` contains:

- `to_text()` — normalizes model content into plain text.
- `extract_images()` — finds nested preview and image paths.
- `extract_result()` — reads the latest structured result for a named tool.
- `merge_results()` — joins specialist answers without exposing internal agent labels.

`files.py` contains `valid_image()`, which permits only supported images inside the configured generated or RAG roots.

Helpers do not call models and do not contain business decisions.

## 7. RAG through MCP

`mcp_server/server.py` is a separate FastMCP application. It imports the Assignment 8 RAG and exposes a narrow authenticated interface.

For `answer_question()`:

1. the Assignment 8 query analyzer creates technical query variants;
2. Qdrant dense search and BM25 retrieve candidates;
3. Reciprocal Rank Fusion combines both rankings;
4. the cross-encoder reranks the candidates;
5. the grounded generator answers from the top contexts; and
6. the MCP result returns answer, sources, locations, and optional image paths.

The RAG Agent never accesses Qdrant directly. This keeps retrieval replaceable and independently testable.

## 8. Component Manager through A2A

`app/integrations/component_client.py` is System A's A2A client. `contact_manager()` discovers and caches System B's Agent Card, sends the supervisor's plain task, waits for completion, and returns exact structured tool calls and results.

`run_component()` is the LangGraph relay node. It has no local model. System B's own Google ADK agent decides which search or purchasing tool to call.

System B starts in `component_manager/server.py`. Google ADK converts the root agent from `component_manager/agent.py` into an A2A server and publishes the Agent Card. Its deterministic tools are in `component_manager/tools.py`; database operations are in `component_manager/db.py`.

The purchase flow is:

```text
Supervisor
  → run_component()
  → System B creates proposal
  → approve_purchase() pauses
  → user approves exact terms
  → run_component() submits proposal
  → System B returns order reference
```

The approval token, total, expiration, spending limit, and idempotency key are checked outside the model.

## 9. Guardrails and artifacts

`app/guardrails.py` protects requests before routing:

- `check_input()` masks sensitive data or blocks unsafe input.
- `mask_data()` is registered under the guardrail action name expected by the configuration.

Tool traces store actions and results, not private chain-of-thought. Supplier part numbers are preserved because completed answers are not passed through generic PII masking. Before an image is public, `valid_image()` confirms its type, existence, and allowed root. FastAPI then exposes it using an artifact ID rather than its local path.

## 10. DigiKey and AP2 implementation, function by function

System B now has one purchasing path. DigiKey supplies searchable product data
and accepts sandbox orders; local SQLite only tracks OAuth tokens, proposals,
and orders.

### `component_manager/digikey.py`

`DigiKeyError` is the safe error type returned across the agent boundary.
`DigiKeyClient.__init__()` accepts an optional HTTP client for tests.
`base_url` chooses sandbox or production Product Information host from settings.
`_http()` returns the injected client or creates a normal asynchronous client.
`_check_config()` fails early when search credentials are missing.
`_access_token()` obtains and caches a two-legged client-credentials token; it
refreshes shortly before expiry. `search()` validates its inputs, calls Product
Information V4, and converts HTTP/provider failures into `DigiKeyError` without
leaking credentials.

`_text()` extracts text from either a string or DigiKey's nested value objects.
`_number()` safely converts provider values to numbers. `_price()` chooses the
highest price-break quantity that does not exceed the requested quantity.
`_variation()` selects a product variation and attaches its applicable price.
`normalize_product()` converts DigiKey's large response into the stable product
card used by the graph and React. `rank_products()` places available, priced,
lower-total offers first. The module-level `client` reuses token state instead
of authenticating from scratch for every tool call.

### `component_manager/oauth.py`

This file implements the separate three-legged OAuth connection required for
ordering. `_base_url()` selects DigiKey's sandbox OAuth host. `_require_config()`
requires the ordering client ID/secret and refuses production ordering.
`_key()` loads the configured Fernet key or creates a permission-restricted,
git-ignored local key. `_fernet()` constructs the encryptor. `_state_hash()`
hashes a one-time OAuth state so the raw value is never stored.

`authorization_url()` creates a random state, stores its hash with a short
expiry, and returns DigiKey's consent URL. `exchange_code()` consumes that state
exactly once, exchanges the short-lived callback code, and stores encrypted
tokens. `_token_request()` performs authorization-code and refresh exchanges.
`_save_tokens()` encrypts access/refresh tokens before SQLite sees them.
`_load_tokens()` decrypts them only inside System B. `access_token()` returns a
valid token and refreshes it when near expiry. `connection_status()` exposes
only configured/connected/sandbox/expiry metadata. `disconnect()` deletes the
stored encrypted authorization.

### `component_manager/purchasing.py`

`PurchaseError` is the safe public failure type. `_now()` supplies timezone-aware
UTC time. `_ap2_key()` loads or generates System B's private EC signing key.
`_checkout_jwt()` signs the AP2 cart as an ES256 JWT. `_hash()` produces the
base64url SHA-256 binding required by the checkout mandate. `_mandates()` builds
the Intent Mandate, Cart Mandate, payment request, and signed Checkout Mandate;
all state explicitly requires user confirmation.

`create_proposal()` refreshes the exact DigiKey part and quantity, verifies price
and stock, creates an expiring proposal, signs its approval token, stores the
AP2 evidence, and returns only public card/approval data. `_payment_mandate()`
runs only after approval and signs the amount, merchant, and user-authorized
DigiKey account. `_order_body()` creates the sandbox Ordering API payload with
the selected part and test-only contact fields.

`place_order()` is the hard transaction boundary. It refuses production,
returns an existing order for a repeated idempotency key, checks proposal state
and expiry, verifies the exact approval token, obtains the user's DigiKey OAuth
token, signs the Payment Mandate, records a `submitting` row, calls DigiKey
Sandbox, and stores either failure or supplier response. `order_status()` reads
that local submission record without making another purchase.

### `component_manager/tools.py` and `agent.py`

These four functions are the only tools visible to the ADK model:

- `search_digikey()` calls the read-only client, normalizes and ranks products,
  removes insufficient-stock offers, and returns product cards.
- `create_digikey_proposal()` is a thin safe wrapper over `create_proposal()`.
- `place_digikey_order()` is a thin safe wrapper over `place_order()` and
  requires proposal ID, approval token, and idempotency key.
- `get_digikey_order()` reads a previously submitted sandbox order.

The wrappers convert expected purchasing exceptions into structured tool
results. `agent.py` gives ADK the four callables and a prompt that makes the
model choose and compare offers, while deterministic code retains authority
over signing, approval, OAuth, and submission. There is no local inventory
store: every availability question goes to DigiKey's live catalog.

### `component_manager/db.py`

`ComponentDB.__init__()` stores the database path. `connect()` creates the
parent directory, opens SQLite, enables dictionary-like rows, and applies the
schema. `close()` releases it. `connection` prevents use before connection.
`_fetch_one()` and `_fetch_all()` are the two reusable query readers.

`save_oauth_state()` and `consume_oauth_state()` implement expiring, one-use
OAuth CSRF protection. `save_oauth_tokens()`, `get_oauth_tokens()`, and
`delete_oauth_tokens()` persist only encrypted authorization payloads.
`insert_digikey_proposal()`, `get_digikey_proposal()`, and
`update_digikey_proposal()` manage AP2 proposals. `get_digikey_order_by_key()`
implements idempotent lookup; `get_digikey_order()`, `insert_digikey_order()`,
and `update_digikey_order()` keep the sandbox order audit record. `get_db()`
creates one process-level connection under a lock; `reset_db()` closes it for
shutdown and isolated tests.

### FastAPI and React connection functions

In `app/api/main.py`, `start_digikey_oauth()` redirects the browser to consent;
`finish_digikey_oauth()` validates the callback and returns the browser to the
React app; `digikey_oauth_status()` returns safe connection metadata; and
`disconnect_digikey()` removes the authorization. The existing `lifespan()`
opens/closes shared services, while `chat_response()` maps the graph's internal
proposal/order state to the public API without returning AP2 tokens or reasoning.

In React, `getDigiKeyStatus()`, `connectDigiKey()`, and `disconnectDigiKey()` in
`web/src/api/client.ts` call those routes. `DigiKeyConnection` queries status,
opens consent, observes the callback query flag, refreshes status, and disconnects
on request. `ProductCards` renders provider image URLs as images and product URLs
as links; paths are not shown. `useConversation()` keeps product/proposal/order
data beside the active thread and resumes the exact paused graph after approval.

### Complete order sequence

```text
User asks to buy
  → supervisor routes to System B through A2A
  → ADK calls search_digikey
  → ADK chooses an exact part
  → ADK calls create_digikey_proposal
  → AP2 intent/cart/checkout evidence is signed and stored
  → System A pauses the thread and React shows exact terms
  → user approves
  → graph creates one idempotency key and resumes System B
  → place_digikey_order validates approval and signs Payment Mandate
  → encrypted DigiKey OAuth authorization supplies the access token
  → DigiKey Sandbox Ordering receives the request
  → System B stores and returns the sandbox reference
  → System A saves the public result in that chat thread
```

The LLM never receives a client secret, OAuth token, private signing key, raw
card field, or direct database connection. It may receive only the opaque
sandbox credential reference needed by the purchasing tool.

### Human-present sandbox card boundary

The purchase approval card now contains a test-card form. This demonstrates the
AP2 Credential Provider role without pretending that DigiKey accepts an external
card token. DigiKey Sandbox is still funded/authorized by the account connected
through three-legged OAuth; the AP2 credential is authorization evidence for the
academic workflow.

`app/payment_vault.py` is deliberately deterministic and contains no model call:

- `CredentialError` is the only safe form-validation exception returned to React.
- `Credential` contains only brand, last four digits, and expiration time. There
  is no field capable of storing PAN, CVV, or card expiry.
- `_digits()` normalizes a field in a temporary local variable.
- `_luhn()` verifies the card checksum without contacting an agent.
- `_brand()` derives display-only metadata from the sandbox prefix.
- `tokenize()` accepts only the documented test card, validates CVV and expiry,
  creates a random `cp_test_...` reference, and immediately loses the raw inputs
  when the function returns. Only the non-sensitive `Credential` remains in RAM.
- `authorize()` checks that the reusable opaque reference exists and has not
  expired. The new AP2 Payment Mandate binds each use to the current proposal.
- `forget()` deletes one saved session payment method on user request.
- `clear()` wipes the in-memory vault during shutdown/tests.

`tokenize_sandbox_card()` in `app/api/main.py` is a separate deterministic route,
`POST /payments/sandbox/tokenize`. It is not the chat endpoint and never calls
LangGraph, an LLM, A2A, ADK, DigiKey, or SQLite. Its response contains only the
opaque ID, brand, last four, expiry timestamp, and `sandbox: true`.

`ApprovalDecision.payment_credential_id` lets React resume the paused graph using
only that opaque reference. `approve_purchase()` calls `authorize()` before it
creates the component-manager task. Consequently, the LLM can see only a random
reference plus `Visa ending in 4242`. `place_digikey_order()` requires the opaque
reference, and `_payment_mandate()` writes that reference—not card data—into a new
signed AP2 Payment Mandate for the current proposal and exact amount.

In React, `PurchaseProposalCard.approveWithCard()` sends the temporary form state
only to the tokenization route, clears all three fields as soon as tokenization
succeeds, and resumes chat using only `credential_id`. `useConversation()` keeps
the returned brand/last-four/reference in memory across proposals. It is not put
in local storage and disappears on page reload or backend restart. The card can
also be replaced or removed through `forgetSandboxCard()`.

The enforced data paths are therefore:

```text
PAN + expiry + CVV
  → POST /payments/sandbox/tokenize
  → validation in payment_vault.py
  → discarded

opaque cp_test reference + brand + last4
  → purchase approval
  → LangGraph
  → A2A / ADK
  → AP2 Payment Mandate
  → DigiKey Sandbox submission
```

Security tests prove that the stored `Credential` has no card-number, CVV, or
expiry attributes; the tokenization response contains none of those fields; a
credential can be explicitly forgotten; and the graph task contains the opaque
reference but not the full test-card string.

## 11. Tests

All tests are under `tests/`:

- API and chat lifecycle tests;
- LangGraph routing and approval tests;
- guardrail tests;
- MCP and A2A integration tests;
- code, 3D model, and wiring tool tests; and
- `tests/component_manager/` for isolated DigiKey and purchasing tests.

The Component Manager fixture creates a fresh temporary SQLite database for each System B test, seeds it, and resets it afterward.

Run everything with:

```bash
PYTHONPATH=. .venv/bin/pytest
```

Run frontend checks with:

```bash
cd web
npm run lint
npm run build
```

## 11. Reading order

For a first complete understanding, read files in this order:

1. `app/config.py`
2. `app/api/schemas.py`
3. `app/api/main.py`
4. `app/chat_service.py`
5. `app/graph.py`
6. `app/helpers/`
7. `agents/`
8. `tools/wiring_tools.py` and `app/integrations/component_client.py`
9. `mcp_server/server.py`
10. `component_manager/agent.py`, `tools.py`, and `db.py`
11. `web/src/hooks/useConversation.ts`
12. `tests/`
