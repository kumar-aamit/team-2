# Machine Downtime Log - OpenShift-compatible Dockerfile

FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

# OpenShift runs as arbitrary UID; group 0 + g+rwX is the standard pattern
COPY --from=builder /install /usr/local
COPY . .

RUN chgrp -R 0 /app \
 && chmod -R g+rwX /app \
 && mkdir -p /data \
 && chgrp -R 0 /data \
 && chmod -R g+rwX /data

ENV PYTHONDONTWRITEBYTECODE=1 \
 PYTHONUNBUFFERED=1 \
 APP_PORT=8742

EXPOSE 8742

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8742/health')" || exit 1

CMD ["python", "-m", "app.main"]