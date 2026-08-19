# React/TypeScript Frontend

The primary frontend for the robotics multi-agent assistant. Built with Vite,
React, TypeScript, and TanStack Query.

This is request/response, not SSE: sending a message or resolving an approval
blocks until the graph run finishes or pauses, same as the FastAPI backend
and the Streamlit app before it. The Activity panel only ever reflects the
*last* turn's tool activity — there is no live event stream to replay.

## Setup

```bash
npm install
cp .env.example .env.local   # override VITE_API_BASE_URL if FastAPI isn't on :8000
npm run dev
```

Start the FastAPI backend first (see the root [README](../README.md)) — the
app creates a thread on load and will show a connection error otherwise.

## Structure

- `src/api/types.ts` — mirrors [`app/api/schemas.py`](../app/api/schemas.py) by hand; keep both in sync.
- `src/api/client.ts` — typed fetch wrapper for the FastAPI application.
- `src/api/hooks.ts` — TanStack Query wrappers for the thread list and thread deletion/creation.
- `src/hooks/useConversation.ts` — orchestrates one conversation: history load, send/resume, pending approvals, and the last turn's images/wiring plan/purchase state.
- `src/components/Sidebar/` — conversation list and management.
- `src/components/ChatPanel/` — messages (rendered as markdown via `react-markdown`/`remark-gfm`), the two approval card types, and the message input.
- `src/components/ActivityPanel/` — wiring plan table, purchase/order status, and the last turn's tool trace.

## Verification

Type-check, lint, and build:

```bash
npx tsc -b
npx oxlint src
npm run build
```

This was also verified against a live backend (real `component_manager` A2A
and `wiring_agent` runs) using a scripted Playwright session — a message
round-trip, and a wiring request that populated the Activity panel's table
from real tool output. That script was a one-off verification aid, not
checked in; re-create it ad hoc if you need to re-verify after a change.
