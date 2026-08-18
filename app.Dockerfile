FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# openscad is a runtime dependency of the visualization agent's shell-out
# tool (tools/openscad_tools.py); it's a system package, not a pip package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openscad \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# mcp_server/ and component_manager/ are intentionally not copied here:
# System A talks to both over the network (MCP over HTTP, System B over
# A2A/REST) rather than importing their code, so this image only needs the
# packages it actually imports.
COPY pyproject.toml pyproject.toml
COPY app app
COPY agents agents
COPY tools tools
COPY guardrails guardrails

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
