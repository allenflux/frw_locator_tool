FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8099

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app.py ./app.py
COPY templates ./templates
COPY static ./static
COPY data ./data

EXPOSE 8099

CMD ["sh", "-c", "uvicorn app:app --host ${APP_HOST} --port ${APP_PORT}"]
