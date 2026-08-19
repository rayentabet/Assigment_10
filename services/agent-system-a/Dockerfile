# Agent System A: LangGraph supervisor and specialists behind FastAPI.
# Build context is this directory, so the service builds independently of the
# rest of the repository.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes,
# so ordinary source edits do not reinstall the whole dependency set.
COPY requirements.txt requirements.txt

# libgl1 and friends are what OpenCascade (build123d's OCP backend) links
# against; without them `import build123d` fails on libGL.so.1. They used to
# arrive incidentally as openscad dependencies, so they must be requested
# explicitly now that openscad is gone. git is only needed to resolve the VCS
# dependency in requirements.txt, so it alone is purged in the same layer.
# --retries/--timeout ride out the transient network stalls this link has
# shown (down to ~9 kB/s), which would otherwise abort the install on pip's
# 15 second default timeout.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git libgl1 libglu1-mesa libxext6 libx11-6 \
    && python -m pip install --no-cache-dir --retries 10 --timeout 120 --upgrade pip \
    && python -m pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

# Imported as top-level packages from WORKDIR, matching how they are imported
# outside the container. `guardrails` holds the NeMo rails config that
# app/guardrails.py resolves relative to the package, so it must sit here.
COPY app app
COPY agents agents
COPY tools tools
COPY guardrails guardrails

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
