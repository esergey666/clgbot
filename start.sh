#!/bin/sh
set -eu

if [ -n "${TELEGRAM_API_ID:-}" ] && [ -n "${TELEGRAM_API_HASH:-}" ]; then
    mkdir -p /app/data/telegram-bot-api /tmp/telegram-bot-api
    telegram-bot-api \
        --api-id="${TELEGRAM_API_ID}" \
        --api-hash="${TELEGRAM_API_HASH}" \
        --local \
        --http-ip-address=127.0.0.1 \
        --http-port=8081 \
        --dir=/app/data/telegram-bot-api \
        --temp-dir=/tmp/telegram-bot-api &
    export TELEGRAM_API_BASE="${TELEGRAM_API_BASE:-http://127.0.0.1:8081}"
fi

exec python -m bot.main
