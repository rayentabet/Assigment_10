#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Manual Docker setup for the Robotics Multi-Agent system - no docker compose.
#
# This does by hand exactly what compose.yaml does for you: create a shared
# network, build each image, then run each container on that network with the
# right env vars, ports, and volumes. Read it top to bottom; every step below
# has a matching block in compose.yaml if you want to compare the two.
#
# Topology - one user-defined bridge network so containers can reach each
# other by container name instead of a hardcoded IP:
#
#   qdrant                  vector DB (official image)
#   mcp-server               RAG, HTTP MCP service              -> qdrant
#   component-manager        System B, A2A JSON-RPC
#   component-manager-rest   System B, REST + SSE (same image as above,
#                             different startup command)
#   app-api                  System A: LangGraph supervisor + FastAPI
#                             -> mcp-server, component-manager, qdrant
# -----------------------------------------------------------------------------

cd "$(dirname "$0")/.."   # run from the Assignment_10/ repo root regardless of caller cwd
REPO_ROOT="$(pwd)"
PARENT_DIR="$(cd .. && pwd)"   # sibling to Assignment_8

NETWORK=robotics-net

echo "== 1. User-defined bridge network =="
# The default 'bridge' network does NOT resolve containers by name; a
# user-defined network runs its own embedded DNS server that does. That's
# what lets app-api later reach "http://component-manager:8002" instead of
# needing to know its IP address.
docker network inspect "$NETWORK" >/dev/null 2>&1 \
  && echo "  '$NETWORK' already exists, reusing it" \
  || docker network create "$NETWORK"

echo "== 2. Named volumes (survive 'docker rm', unlike the container's own writable layer) =="
for vol in qdrant_data component_manager_data app_chat_data app_generated; do
  docker volume inspect "$vol" >/dev/null 2>&1 || docker volume create "$vol"
done

echo "== 3. Qdrant (vector DB) =="
docker run -d --name qdrant \
  --network "$NETWORK" \
  -p 6333:6333 \
  -v qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest

echo "== 4. Build + run the RAG MCP server =="
# Build context is the PARENT directory (InMind/), not Assignment_10 - the
# image needs source from both Assignment_8 (the RAG corpus it indexes and
# serves images from) and Assignment_10 (mcp_server/). -f is relative to the
# current directory (Assignment_10/); the context path after it is relative
# too. This mirrors compose.yaml's mcp-server "context: .. / dockerfile:
# Assignment_10/Dockerfile" exactly.
docker build -f Dockerfile -t arduino-rag-mcp:local ..
docker run -d --name mcp-server \
  --network "$NETWORK" \
  --env-file "$PARENT_DIR/Assignment_8/.env" \
  --env-file .env \
  -e RAG_PATH=/app/assignment_8 \
  -e QDRANT_URL="http://qdrant:6333" \
  -e MCP_TRANSPORT=http -e MCP_HOST=0.0.0.0 -e MCP_PORT=8000 \
  -p 8001:8000 \
  arduino-rag-mcp:local

echo "== 5. Build + run System B: the A2A server =="
docker build -f component_manager/Dockerfile -t component-manager:local .
docker run -d --name component-manager \
  --network "$NETWORK" \
  --env-file component_manager/.env \
  -e ADVERTISED_HOST=component-manager \
  -p 8002:8002 \
  -v component_manager_data:/app/component_manager/data \
  component-manager:local

echo "== 6. Same image, different startup command: System B's REST + SSE wrapper =="
# One built image, two running containers - the whole point of separating
# "build an image" from "run a container" instead of conflating them.
docker run -d --name component-manager-rest \
  --network "$NETWORK" \
  --env-file component_manager/.env \
  -p 8003:8003 \
  -v component_manager_data:/app/component_manager/data \
  component-manager:local \
  python -m uvicorn component_manager.rest_api:app --host 0.0.0.0 --port 8003

echo "== 7. Build + run System A: the LangGraph supervisor + FastAPI app =="
docker build -f app.Dockerfile -t robotics-app-api:local .
docker run -d --name app-api \
  --network "$NETWORK" \
  --env-file .env \
  -e MCP_SERVER_URL="http://mcp-server:8000/mcp" \
  -e COMPONENT_MANAGER_A2A_URL="http://component-manager:8002" \
  -e QDRANT_URL="http://qdrant:6333" \
  -e RAG_PROJECT_PATH=/app/assignment_8 \
  -p 8000:8000 \
  -v app_chat_data:/app/data \
  -v app_generated:/app/generated \
  -v "$PARENT_DIR/Assignment_8:/app/assignment_8:ro" \
  robotics-app-api:local

cat <<EOF

All containers are up on network '$NETWORK':
  docker ps --filter network=$NETWORK

  System A (chat API):      http://localhost:8000/docs
  System B (A2A card):      http://localhost:8002/.well-known/agent-card.json
  System B (REST + SSE):    http://localhost:8003/health
  RAG MCP server:           http://localhost:8001/mcp
  Qdrant dashboard:         http://localhost:6333/dashboard

Tear it all down with: scripts/docker-manual-down.sh
EOF
