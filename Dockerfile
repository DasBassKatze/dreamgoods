# DreamGoods — образ сервиса для сервера (Linux + Docker). Интерфейс уже собран в dreamgoods/web, Node.js не нужен.
# Запуск вместе с базой:  docker compose --profile server up -d --build   (подробно — README, «Запуск на сервере»)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini run_dreamgoods.py ./
COPY migrations ./migrations
COPY dreamgoods ./dreamgoods

# файлы, журналы и выгрузки — в томах (см. docker-compose.yml), чтобы переживали пересборку образа
VOLUME ["/app/data", "/app/logs", "/app/exports"]
EXPOSE 8090
CMD ["python", "run_dreamgoods.py", "--no-browser"]
