# Robotics Multi-Agent MCP System

This project coordinates four specialists through a LangGraph supervisor:

- an MCP-backed robotics RAG agent;
- a code generation and validation agent;
- an OpenSCAD robot visualization agent;
- a general-purpose agent.

The Arduino RAG MCP server runs as a Dockerized Streamable HTTP service. Both
LangGraph and OpenCode connect to the same network endpoint rather than starting
separate MCP subprocesses over stdio.

## Prerequisites

- Python 3.11 or newer
- OpenSCAD available as `openscad`
- Qdrant and the existing Assignment 8 RAG dependencies

The current machine only exposes Python 3.9, so install Python 3.11 before
creating the virtual environment.

## Initial setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
pytest
```

Add API keys to `.env`; never commit that file.

Generate a bearer token for the MCP server and add it as `MCP_AUTH_TOKEN` in
`.env`:

```bash
openssl rand -hex 32
```

## Development order

1. Test the RAG tools in `mcp_server/server.py`.
2. Implement restricted code and OpenSCAD tools.
3. Implement each specialist independently.
4. Assemble the supervisor graph.
5. Run the evaluation suite and document routing failures.

## Generated files

Code is confined to `generated/code/`. OpenSCAD source and PNG previews are
confined to `generated/robots/<model-name>/`.

## Evaluation dashboard

Each evaluation is saved under `evaluation/runs/<timestamp>_<run-name>/` with
its `results.csv` and `metadata.json`. The latest results are also written to
`evaluation/results.csv`.

Run an evaluation from the terminal:

```bash
PYTHONPATH=. .venv/bin/python evaluation/run_evaluation.py --run-name baseline
```

Open the saved runs in Streamlit:

```bash
.venv/bin/streamlit run evaluation/dashboard.py
```

## Human approval checkpoint

The `human_approval` graph node pauses before `coding_agent` or
`robot_visualization_agent` runs, because those specialists can write generated
files or start an expensive OpenSCAD render. The CLI shows the pending action and
resumes the same checkpointed thread with `Command(resume={"approved": ...})`.

Try it with:

```bash
PYTHONPATH=. .venv/bin/python -m app.cli
```

Enter `Create an OpenSCAD model of a two-wheeled robot`. At the approval prompt,
answer `n` to verify cancellation, then run it again and answer `y` to continue.
Read-only routes such as `Explain how an ultrasonic sensor works` do not pause.

## RAG MCP tools

The server currently exposes:

- `search_documents`: retrieve reranked contexts and their source metadata;
- `answer_question`: generate a grounded answer and return its contexts;
- `show_image`: display the image referenced by a retrieved `image_path`;
- `corpus://metadata`: describe the corpus and retrieval capabilities.

`show_image` only accepts supported image files inside the configured
`RAG_PROJECT_PATH`. Pass it the path exactly as returned by a search or answer.

## Dockerized HTTP MCP server

Qdrant must already be running with host port `6333` published. The Compose
configuration connects to it from Docker through
`http://host.docker.internal:6333` and injects the Assignment 8 and Assignment
10 `.env` files at runtime. Neither `.env` is copied into the image;
`Dockerfile.dockerignore` excludes secrets, Git metadata, virtual environments,
caches, generated output, and the local Qdrant snapshot.

The build context must be the parent `InMind` directory because the image needs
code from both assignments. The container installs the narrow dependency set in
`mcp_server/requirements-http.txt`, rather than installing the evaluation UI and
multi-agent application packages that the MCP process does not use. Compose
handles the parent build context automatically:

```bash
docker compose up --build -d mcp-server
docker compose logs -f mcp-server
```

The MCP endpoint is then available at:

```text
http://127.0.0.1:8001/mcp
```

Verify MCP tool discovery over the network:

```bash
MCP_INTEGRATION_TEST_URL=http://127.0.0.1:8001/mcp \
  MCP_AUTH_TOKEN="$MCP_AUTH_TOKEN" \
  .venv/bin/pytest tests/test_mcp_connection.py
```

The HTTP endpoint requires `Authorization: Bearer <token>`. LangGraph reads the
token from `.env`, while OpenCode expands `{env:MCP_AUTH_TOKEN}` in
`opencode.json`; export the variable before starting OpenCode:

```bash
export MCP_AUTH_TOKEN="your-generated-token"
opencode mcp list
```

The token prevents clients without the shared secret from listing resources or
calling tools. It does not encrypt traffic, replace HTTPS for a remote
deployment, protect a token exposed in logs or a compromised client, provide
per-user permissions, or make the tools themselves safe. The included static
token verifier is appropriate for this local demonstration; production should
use HTTPS and short-lived OAuth/JWT tokens with issuer, audience, expiry, and
scope validation.

Run the multi-agent CLI only after the container is ready:

```bash
PYTHONPATH=. .venv/bin/python -m app.cli
```

## FastAPI chat service

FastAPI is the main application interface. Start it after the MCP server is ready:

```bash
PYTHONPATH=. .venv/bin/uvicorn app.api.main:app --reload --port 8000
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.
Create a thread, then send messages using its returned ID:

Conversation checkpoints are persisted in `data/chat_history.sqlite` by default,
so thread state and paused approval requests survive API restarts. Override the
location with `CHAT_DATABASE_PATH` in `.env`.

```bash
curl -X POST http://127.0.0.1:8000/threads

curl -X POST http://127.0.0.1:8000/threads/THREAD_ID/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"Explain how an ultrasonic sensor works"}'
```

Retrieve the public user/assistant history for that thread:

```bash
curl http://127.0.0.1:8000/threads/THREAD_ID/messages
```

Delete the thread, its public history, artifacts, and LangGraph checkpoints:

```bash
curl -X DELETE http://127.0.0.1:8000/threads/THREAD_ID
```

If the response status is `approval_required`, continue the same checkpoint:

```bash
curl -X POST http://127.0.0.1:8000/threads/THREAD_ID/resume \
  -H 'Content-Type: application/json' \
  -d '{"approved":true}'
```

## Streamlit chat frontend

Keep FastAPI running, then start the frontend in a second terminal:

```bash
PYTHONPATH=. .venv/bin/streamlit run frontend/streamlit_app.py
```

The UI creates and retains a thread ID, reloads SQLite-backed history, sends chat
messages through FastAPI, and displays approval controls for paused coding or
visualization actions. Set `API_BASE_URL` in `.env` if FastAPI is not running at
`http://127.0.0.1:8000`.

Stop the MCP service without affecting the separately running Qdrant container:

```bash
docker compose down
```
