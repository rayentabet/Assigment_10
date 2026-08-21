# Custom MCP server exposing the Arduino RAG as tools.
#
# The build context is this service directory. The runtime RAG package and
# referenced corpus images are embedded under rag/, so no sibling repository
# is required.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_DOWNLOAD_TIMEOUT=120 \
    RAG_PATH=/app/rag \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app

# Requirements alone first, so the expensive dependency layer is not
# invalidated every time the RAG corpus or the server source changes.
COPY requirements.txt requirements.txt

# --retries/--timeout ride out transient stalls: this link has been observed
# dropping to ~9 kB/s mid-download, which kills an otherwise fine build after
# pip's 15s default timeout. Set on the RUN rather than as an ENV so editing
# them never invalidates the cached layers above.
RUN PIP="python -m pip install --no-cache-dir --retries 10 --timeout 120" \
    && $PIP --upgrade pip \
    && $PIP --index-url https://download.pytorch.org/whl/cpu torch \
    && $PIP -r requirements.txt

# Bake the reranker weights into the image so the container never downloads a
# model at request time. Backs off between attempts rather than retrying
# immediately, since the failure this guards against is a slow or flapping
# link rather than an instantly-retryable error.
RUN for attempt in 1 2 3 4 5; do \
        python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2')" && exit 0; \
        echo "reranker download attempt $attempt failed; retrying in $((attempt * 15))s"; \
        sleep $((attempt * 15)); \
    done; \
    echo "reranker download failed after 5 attempts" >&2; \
    exit 1

COPY mcp_server /app/mcp_server
COPY rag /app/rag

EXPOSE 8000

CMD ["python", "-m", "mcp_server.server"]
