#!/usr/bin/env bash
# Bootstrap the bot on a fresh Ubuntu host.
#
# Usage:
#   ./scripts/deploy.sh
#
# Requires an .env file in the repo root with all required vars set.
# Will install docker if missing.

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    echo "❌ .env not found. Copy .env.example, fill in secrets, then re-run." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "📦 Installing docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "⚠️  You were added to the docker group. Log out and log back in, then re-run."
    exit 0
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "❌ docker compose v2 plugin missing. Install docker-compose-plugin." >&2
    exit 1
fi

chmod 600 .env

echo "🔨 Building images..."
docker compose build

echo "🚀 Starting services..."
docker compose up -d

echo "⏳ Waiting for postgres to report healthy..."
for i in {1..30}; do
    cid=$(docker compose ps -q db || true)
    if [[ -n "$cid" ]]; then
        status=$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "starting")
        if [[ "$status" == "healthy" ]]; then
            echo "✅ DB healthy."
            break
        fi
    fi
    sleep 2
done

echo "🛠  Running migrations..."
docker compose exec -T bot alembic upgrade head || echo "⚠️  alembic skipped (sqlite or first run)"

echo "📜 Tail logs with:  docker compose logs -f bot"
