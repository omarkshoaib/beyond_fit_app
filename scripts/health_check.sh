#!/usr/bin/env bash
# Verifies the bot container is up + the db is healthy.
# Uses `docker inspect` (stable across compose minor versions) instead of
# `docker compose ps --format json` which has shifted output shape.
# Returns 0 on healthy, 1 otherwise. Prints status to stdout.

set -uo pipefail

cd "$(dirname "$0")/.."

ok=true

bot_cid=$(docker compose ps -q bot 2>/dev/null || true)
db_cid=$(docker compose ps -q db 2>/dev/null || true)

if [[ -z "$bot_cid" ]]; then
    echo "❌ bot container not found"
    ok=false
else
    bot_state=$(docker inspect --format '{{.State.Status}}' "$bot_cid" 2>/dev/null || echo "missing")
    if [[ "$bot_state" != "running" ]]; then
        echo "❌ bot container state=$bot_state"
        ok=false
    fi
fi

if [[ -z "$db_cid" ]]; then
    echo "❌ db container not found"
    ok=false
else
    db_health=$(docker inspect --format '{{.State.Health.Status}}' "$db_cid" 2>/dev/null || echo "none")
    if [[ "$db_health" != "healthy" ]]; then
        echo "❌ db health=$db_health"
        ok=false
    fi
fi

if $ok; then
    echo "✅ bot stack healthy"
    exit 0
fi
exit 1
