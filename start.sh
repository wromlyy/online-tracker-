#!/bin/bash
set -u

echo "▶️  Запуск Telegram-монитора и WhatsApp-приёмника…"

python telegram_monitor.py &
PY_PID=$!

node whatsapp_notifier.js &
NODE_PID=$!

# ждём первую смерть — если один упал, гасим второй, контейнер перезапустится
cleanup() {
    kill $PY_PID $NODE_PID 2>/dev/null || true
    wait
}
trap cleanup INT TERM

wait -n
echo "⚠️  Один из процессов завершился — перезапуск контейнера"
cleanup
exit 1
