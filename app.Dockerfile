FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app


COPY pyproject.toml pyproject.toml
COPY app app
COPY agents agents
COPY tools tools
COPY guardrails guardrails


# libgl1 and friends are the runtime OpenCascade (build123d's OCP) links
# against; without them `import build123d` fails on libGL.so.1. They used to
# arrive incidentally as openscad dependencies, so they must be requested
# explicitly now that openscad is gone. git is only needed to resolve the VCS
# dependency in pyproject.toml, so it alone is purged in the same layer.
# --retries/--timeout ride out the transient network stalls this link has shown
# (down to ~9 kB/s), which would otherwise abort the install on pip's 15s
# default timeout.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git libgl1 libglu1-mesa libxext6 libx11-6 \
    && python -m pip install --no-cache-dir --retries 10 --timeout 120 --upgrade pip \
    && python -m pip install --no-cache-dir --retries 10 --timeout 120 -e . \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
