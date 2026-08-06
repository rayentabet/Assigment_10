FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_XET=1 \
    RAG_PATH=/app/assignment_8 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app

COPY Assignment_8 /app/assignment_8
COPY Assignment_10 /app/assignment_10

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu torch \
    && python -m pip install --no-cache-dir \
        -r /app/assignment_10/mcp_server/requirements-http.txt

# Download the reranker during the build instead of blocking the first user query.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2')"

WORKDIR /app/assignment_10

EXPOSE 8000

CMD ["python", "mcp_server/server.py"]
