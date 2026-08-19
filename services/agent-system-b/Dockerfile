# Agent System B: independent Google ADK Component Manager.
#
# Serves two surfaces from this one container: the A2A JSON-RPC endpoint that
# System A calls across the network (8002), and its own REST/SSE chat API
# (8003). They stay on separate ports so neither one's routes shadow the
# other's, and so System A's A2A URL needs no path prefix.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8002 \
    DATABASE_PATH=component_manager/data/component_manager.sqlite

WORKDIR /app

COPY requirements.txt requirements.txt

# git resolves the VCS-pinned AP2 dependency, then is purged in the same layer
# so it does not ship in the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && python -m pip install --no-cache-dir --retries 10 --timeout 120 --upgrade pip \
    && python -m pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

COPY component_manager component_manager

EXPOSE 8002 8003

# `wait -n` returns as soon as either server exits, so the container stops
# instead of lingering half-dead with only one surface still answering.
CMD ["sh", "-c", "python -m uvicorn component_manager.server:app --host 0.0.0.0 --port 8002 & python -m uvicorn component_manager.rest_api:app --host 0.0.0.0 --port 8003 & wait -n"]
