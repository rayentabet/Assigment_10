FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_DOWNLOAD_TIMEOUT=120 \
    RAG_PATH=/app/assignment_8 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app

COPY Assignment_8 /app/assignment_8
COPY Assignment_10 /app/assignment_10

# --retries/--timeout ride out transient stalls: this link has been observed
# dropping to ~9 kB/s mid-download, which kills an otherwise fine build after
# pip's 15s default timeout. Set on the RUN rather than as an ENV so editing
# them never invalidates the cached layers above.
RUN PIP="python -m pip install --no-cache-dir --retries 10 --timeout 120" \
    && $PIP --upgrade pip \
    && $PIP --index-url https://download.pytorch.org/whl/cpu torch \
    && $PIP -r /app/assignment_10/mcp_server/requirements-http.txt


RUN for attempt in 1 2 3; do \
        python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2')" && exit 0; \
        echo "reranker download attempt $attempt failed; retrying"; \
        sleep 10; \
    done; \
    echo "reranker download failed after 3 attempts" >&2; \
    exit 1

WORKDIR /app/assignment_10

EXPOSE 8000

CMD ["python", "mcp_server/server.py"]
