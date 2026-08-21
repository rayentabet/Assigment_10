# Docker setup

The canonical deployment definition is the root `docker-compose.yml`.

## Services

| Compose service | Host port | Purpose |
|---|---:|---|
| `vector-db` | 6333 | Qdrant vector storage |
| `mcp-server` | 8001 | RAG MCP server; container port 8000 |
| `agent-system-b` | 8002, 8003 | ADK/A2A Component Manager and REST API |
| `agent-system-a` | 8010 | FastAPI and LangGraph; container port 8000 |
| `frontend` | 5173 | Optional nginx-hosted production frontend |

System B intentionally exposes A2A and REST from one container. System A calls
services through Compose DNS names, never through host `localhost` addresses.

## Start

For the normal setup, where React runs locally:

```bash
docker compose up -d --build vector-db mcp-server agent-system-b agent-system-a
cd services/frontend
npm run dev
```

To run the built frontend in Docker as well:

```bash
docker compose up -d --build
```

## Service-to-service URLs

Compose overrides local loopback defaults with these internal URLs:

| Consumer | URL |
|---|---|
| Agent A to MCP | `http://mcp-server:8000/mcp` |
| Agent A to System B A2A | `http://agent-system-b:8002` |
| Agent A to System B REST | `http://agent-system-b:8003` |
| Agent A/MCP to Qdrant | `http://vector-db:6333` |

The browser runs outside the Compose network and therefore connects to Agent A
at `http://localhost:8010`.

## Persistent data

Compose uses named volumes for:

- `qdrant_data`: vector index;
- `component_manager_data`: System B OAuth, approval and ordering data;
- `app_chat_data`: Agent A conversation checkpoints;
- `app_generated`: generated code and models.

The RAG runtime and referenced images are stored inside
`services/mcp-server/rag/`. Agent A mounts that directory read-only so it can
serve images selected by MCP. On a fresh Qdrant volume, the MCP process restores
`services/mcp-server/qdrant/arduino_rag.snapshot` before accepting requests.

## Common commands

```bash
docker compose config --quiet
docker compose ps
docker compose logs -f agent-system-a
docker compose up -d --build agent-system-a
docker compose restart agent-system-a
docker compose down
```

Use `docker compose down -v` only when persistent application data should be
deleted intentionally.

## Secrets

Root application secrets come from `.env`; System B secrets come from
`services/agent-system-b/.env`. Dockerfiles and ignore files prevent these
files from being copied into images. DigiKey OAuth tokens remain encrypted in
the System B volume. Lithic and model-provider keys stay server-side.
