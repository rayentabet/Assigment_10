# Servo — React/TypeScript Frontend

The primary frontend for Servo, the robotics multi-agent assistant. Built
with Vite, React, TypeScript, and TanStack Query.

Sending a message or resolving an approval streams over SSE
(`POST /threads/{id}/messages/stream`, `/resume/stream`): the Activity panel's
tool trace and route history update as each LangGraph node completes, instead
of only once the whole turn finishes or pauses. The final assistant answer
still only appears once, after the backend's output guardrail has checked it
— only intermediate routing/tool-call progress streams live, never raw model
tokens. The non-streaming `POST /threads/{id}/messages` and `/resume`
endpoints still exist and behave exactly as before (used by `cli.py`, the
evaluation harness, and plain `curl`), the frontend just no longer uses them.

## Setup

```bash
npm install
cp .env.example .env.local   # override VITE_API_BASE_URL if FastAPI isn't on :8000
npm run dev
```

Start the FastAPI backend first (see the root [README](../../README.md)) — the
app creates a thread on load and will show a connection error otherwise.

## Structure

- `src/api/types.ts` — mirrors [Agent A's schemas](../agent-system-a/app/api/schemas.py) by hand; keep both in sync.
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
