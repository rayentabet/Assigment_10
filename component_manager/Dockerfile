

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8002 \
    DATABASE_PATH=component_manager/data/component_manager.sqlite

WORKDIR /app

COPY component_manager/requirements.txt component_manager/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# catalog.py reads tools/data/components.json to share component identities
# with the Wiring Agent, so both must keep the same relative layout.
COPY tools/data tools/data
COPY component_manager component_manager

EXPOSE 8002

CMD ["python", "-m", "uvicorn", "component_manager.server:app", "--host", "0.0.0.0", "--port", "8002"]
