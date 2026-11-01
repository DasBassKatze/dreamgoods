#!/usr/bin/env bash
# DreamGoods на сервере: запустить контейнеры без обновления кода (например, после остановки).
#   ./server-start.sh         — запустить
#   ./server-start.sh stop    — остановить (данные сохраняются)
#   ./server-start.sh restart — перезапустить
#   ./server-start.sh logs    — журнал сервиса в реальном времени (выход — Ctrl+C)
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-start}" in
  start)   docker compose --profile server up -d ;;
  stop)    docker compose --profile server down ;;
  restart) docker compose --profile server restart ;;
  logs)    exec docker compose logs -f --tail 50 app ;;
  *)       echo "Использование: $0 [start|stop|restart|logs]" >&2; exit 1 ;;
esac
docker compose --profile server ps
