# Dockerizing the stack: two methods

This documents both ways to run the whole system in containers, as required
for the Docker assignment: a manual, step-by-step method using plain `docker`
commands and a user-defined network, and the equivalent `docker compose`
method. Both methods produce the exact same five containers on the exact same
network topology, so you can read either one to understand the other.

## Topology

```
                         robotics-net (user-defined bridge network)

  ┌─────────┐      ┌────────────┐      ┌────────────────────┐      ┌──────────────────────┐
  │ qdrant  │◄─────┤ mcp-server │◄─────┤     app-api          │─────►│ component-manager     │
  │ (vector │      │ (RAG, HTTP │      │ (System A: LangGraph │      │ (System B: A2A)       │
  │  DB)    │      │  MCP)      │      │  supervisor+FastAPI) │      └──────────────────────┘
  └─────────┘      └────────────┘      │                       │──────►┌────────────────────────┐
                                        └───────────────────────┘      │ component-manager-rest │
                                                                        │ (System B: REST+SSE)   │
                                                                        └────────────────────────┘
```

- **qdrant** — the vector database mcp-server indexes into and queries.
- **mcp-server** — the RAG MCP HTTP service (`mcp_server/server.py`); already had its own Dockerfile before this stack was extended.
- **component-manager** — System B's A2A JSON-RPC server (`component_manager/server.py`).
- **component-manager-rest** — System B's REST + SSE server (`component_manager/rest_api.py`). Same built image as `component-manager`, just started with a different command — one image, two running containers, which is the point of separating "build an image" from "run a container".
- **app-api** — System A: the LangGraph supervisor behind FastAPI (`app/api/main.py`). New in this stack; talks to the other three over the network instead of importing their code.

All five containers sit on one **user-defined bridge network**. That's the
detail everything else hinges on: Docker's default `bridge` network does not
give containers DNS resolution by name, only a user-defined one does (via an
embedded DNS server Docker runs for that network). That's why `app-api` can
reach System B at the URL `http://component-manager:8002` — `component-manager`
resolves to that container's internal IP purely because both containers are
on the same user-defined network, nothing more.

## Method 1: manual (`scripts/docker-manual-up.sh`)

Run:

```bash
./scripts/docker-manual-up.sh      # bring everything up
./scripts/docker-manual-down.sh    # tear it down (add --volumes to also wipe data)
```

Read the script — it's the same six moves for every service, repeated:

1. **`docker network create robotics-net`** — once, before any container. This has to happen before any `docker run --network robotics-net ...`, or that flag fails.
2. **`docker volume create <name>`** — once per thing that must survive a container being removed (Qdrant's index, System B's SQLite DBs, System A's chat history and generated files). A container's own writable layer disappears with `docker rm`; a named volume doesn't.
3. **`docker build -f <Dockerfile> -t <image>:local <context>`** — turns a Dockerfile + build context into an image. Note `mcp-server`'s build context is the *parent* directory (`..`), not `Assignment_10/` — its image needs source from both `Assignment_8/` (the RAG corpus) and `Assignment_10/mcp_server/`. `app-api` and `component-manager` only need `Assignment_10/`, so their context is `.`.
4. **`docker run -d --name <name> --network robotics-net ...`** — starts a container from that image, attached to the shared network under a name other containers will use to reach it.
5. **`--env-file <path>`** — injects environment variables from a file at container start, without baking secrets into the image itself (an image built with `COPY .env .env` would leak API keys to anyone who later pulls that image). You can pass `--env-file` more than once; later files don't overwrite earlier ones for keys they don't define.
6. **`-p <host>:<container>`** — publishes a container port to the host's loopback interface, so you can `curl localhost:8000` from outside Docker entirely. This is unrelated to how containers reach *each other* — that's the network from step 1, not the port mapping.

The one thing this method does that's easy to forget: container-to-container
URLs use the **container's internal port**, not the published host port.
`app-api` reaches System B's REST wrapper at `http://component-manager-rest:8003`
(container's own port) even though the host-side mapping is also `8003:8003`
— those two `8003`s are coincidence, not the same number for a reason.

## Method 2: docker compose (`compose.yaml`)

```bash
docker compose up --build -d
docker compose logs -f app-api
docker compose down              # add -v to also remove named volumes
```

`docker compose` is doing exactly what the manual script does, just reading
it from a declarative file instead of executing it as an imperative sequence
of commands:

- Every service in `compose.yaml` gets attached to one implicit network Compose creates automatically (named `<project>_default`) — you get the manual method's step 1 for free, without writing `docker network create` yourself.
- `volumes:` at the bottom (`qdrant_data`, `component_manager_data`, `app_chat_data`, `app_generated`) are declared once and referenced by name in each service — same effect as step 2.
- `build:` under a service is step 3; `image:` names what to tag it. If you set both, `docker compose build` uses `build:` and tags the result with `image:`, so `docker compose up` on a later run can skip rebuilding.
- Compose starts each container automatically after `docker compose up` — that's step 4, minus you typing `docker run` per service.
- `env_file:` and `environment:` under each service are steps 5 and (partially) the `-e` flags — `environment:` entries win over `env_file:` values for the same key, which is how, for example, `app-api`'s `environment.MCP_SERVER_URL` overrides anything with that name that might be sitting in `.env`.
- `ports:` is step 6, same syntax family.
- **`depends_on:`** has no equivalent in the manual script other than *the order you type the commands in* — Compose uses it to decide startup order. Important nuance for the review: by default `depends_on` only waits for the *container process to start*, not for the application inside it to be ready to accept connections. `app-api` listing `mcp-server`, `component-manager`, and `qdrant` under `depends_on` guarantees Docker starts those containers first, but not that FastAPI/uvicorn or Qdrant have finished initializing before `app-api` sends its first request. In this stack that's usually fine because the app doesn't call out to those services until the first chat message arrives, well after startup — but it's the reason production Compose files add `healthcheck:` blocks and `depends_on: { condition: service_healthy }` instead.

## Environment variables that changed for containers vs. local runs

Everything below defaults to a `127.0.0.1` URL in `.env.example`, because
that's correct when you run each process directly on your machine. Inside
Docker, `127.0.0.1` from one container's point of view is *that container
itself*, not its neighbor — so every cross-service URL gets overridden to the
neighbor's **container name** instead, both in `compose.yaml`'s
`environment:` blocks and the manual script's `-e` flags:

| Variable | Local default | Inside `robotics-net` |
|---|---|---|
| `QDRANT_URL` (used by `mcp-server`, `app-api`) | `http://127.0.0.1:6333` | `http://qdrant:6333` |
| `MCP_SERVER_URL` (used by `app-api`) | `http://127.0.0.1:8001/mcp` | `http://mcp-server:8000/mcp` — note the **container-internal** port 8000, not the published host port 8001 |
| `COMPONENT_MANAGER_A2A_URL` (used by `app-api`) | `http://127.0.0.1:8002` | `http://component-manager:8002` |
| `ADVERTISED_HOST` (used by `component-manager`, for its A2A agent card) | `127.0.0.1` | `component-manager` |
| `RAG_PROJECT_PATH` (used by `app-api`, to serve images the RAG already found) | an absolute path on your machine | `/app/assignment_8` — matches the read-only bind mount `../Assignment_8:/app/assignment_8:ro` |

## Why System A (`app-api`) is plain HTTP inside Docker, not HTTPS

Locally, `app/api/main.py` is normally started with
`--ssl-keyfile/--ssl-certfile` against a self-signed cert in `certs/`, so
the browser talks to `https://localhost:8000`. Inside Docker it's started
without those flags — plain HTTP on the shared network, matching how
`mcp-server` and `component-manager` already run. If you point the React
frontend (still run locally, not containerized here) at the dockerized
backend, set `VITE_API_BASE_URL=http://localhost:8000` in `web/.env` (or
however you configure it) to match — the default in
`web/src/api/client.ts` is still `https://localhost:8000`, since that's
correct for the non-Docker local flow.

## What's read-only vs. writable

- `../Assignment_8:/app/assignment_8:ro` — `app-api` only ever *reads*
  images that the RAG already located; it never writes into the corpus.
- `app_chat_data:/app/data`, `app_generated:/app/generated`,
  `component_manager_data:/app/component_manager/data`,
  `qdrant_data:/qdrant/storage` — all writable named volumes, because each
  backs a SQLite database or generated output that must survive a
  container restart.

## Files

- `app.Dockerfile` / `app.Dockerfile.dockerignore` — System A's image.
- `component_manager/Dockerfile` — System B's image (used by both `component-manager` and `component-manager-rest`, unchanged by this work beyond the new REST module it now ships).
- `Dockerfile` / `Dockerfile.dockerignore` — mcp-server's image, pre-existing.
- `compose.yaml` — the compose method.
- `scripts/docker-manual-up.sh` / `scripts/docker-manual-down.sh` — the manual method.
