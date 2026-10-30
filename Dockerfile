FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY ui ./ui
COPY scripts ./scripts
COPY evaluation ./evaluation
COPY n8n ./n8n

RUN pip install --no-cache-dir -e .

ENV DEMO_MODE=true \
    DATABASE_URL=sqlite:////app/data/paintops.db \
    CHECKPOINT_DB_PATH=/app/data/checkpoints/langgraph.db \
    SOP_DIR=/app/data/sops \
    CHROMA_DIR=/app/data/chroma \
    PAINTOPS_API_BASE=http://api:8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000 8501

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
