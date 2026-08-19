FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8002 \
    DATABASE_PATH=component_manager/data/component_manager.sqlite

WORKDIR /app

COPY component_manager/requirements.txt component_manager/requirements.txt


RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r component_manager/requirements.txt \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*


COPY tools/data tools/data
COPY component_manager component_manager

EXPOSE 8002

CMD ["python", "-m", "uvicorn", "component_manager.server:app", "--host", "0.0.0.0", "--port", "8002"]
