FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8099

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app.py ./app.py
COPY templates ./templates
COPY static ./static
COPY data ./data
COPY workflow_audit_config.json ./workflow_audit_config.json

EXPOSE 8099

CMD ["sh", "-c", "uvicorn app:app --host ${APP_HOST} --port ${APP_PORT}"]
