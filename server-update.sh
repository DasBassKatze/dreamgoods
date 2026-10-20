#!/usr/bin/env bash
# DreamGoods на сервере: забрать свежий код из GitHub и пересобрать/перезапустить контейнеры.
# Запуск:  ./server-update.sh            (из любой папки — скрипт сам перейдёт в папку проекта)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Нет файла .env в $(pwd) — положите настройки сюда и запустите снова." >&2
  exit 1
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
before="$(git rev-parse --short HEAD)"
echo "== Обновление кода (ветка $branch) =="
# логин и токен GitHub git берёт из сохранённых учётных данных (см. README, «Запуск на сервере»)
git pull --ff-only
after="$(git rev-parse --short HEAD)"
if [ "$before" = "$after" ]; then
  echo "Новых изменений нет ($after)."
else
  echo "Обновлено: $before → $after"
  git log --oneline "$before..$after" | head -20
fi

echo "== Сборка и перезапуск контейнеров =="
docker compose --profile server up -d --build

echo "== Состояние =="
docker compose --profile server ps
echo
echo "Последние строки журнала сервиса:"
docker compose logs --tail 15 app || true
port="$(grep -E '^DREAMGOODS_PUBLIC_PORT=' .env | cut -d= -f2 || true)"
echo
echo "Готово. Сайт: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${port:-8090}"
