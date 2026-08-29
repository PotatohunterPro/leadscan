# LeadScan — imagem mínima (python slim + curl p/ healthcheck).
# SEM volume de código de fora: o build faz COPY . . direto do repositório.
# Atualizar é sempre: git pull && docker compose up -d --build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl é usado pelo healthcheck do docker-compose
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY static /app/static
COPY templates /app/templates

RUN mkdir -p /app/data/fotos

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
