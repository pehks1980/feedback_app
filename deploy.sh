#!/usr/bin/env bash

set -euo pipefail

APP_SERVICE="web"
DB_PATH="/app/data/feedback.db"
BACKUP_DIR="./backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_PATH="${BACKUP_DIR}/feedback_${TIMESTAMP}.db"

mkdir -p "${BACKUP_DIR}"

echo "Checking running container..."
CONTAINER_ID="$(docker compose ps -q "${APP_SERVICE}" || true)"

if [ -n "${CONTAINER_ID}" ]; then
    echo "Creating SQLite backup at ${BACKUP_PATH}"
    if docker compose exec -T "${APP_SERVICE}" test -f "${DB_PATH}"; then
        docker compose exec -T "${APP_SERVICE}" sh -c "cat '${DB_PATH}'" > "${BACKUP_PATH}"
    else
        echo "No database file found at ${DB_PATH}; skipping backup."
    fi
else
    echo "No running ${APP_SERVICE} container found; skipping backup."
fi

echo "Pulling latest code..."
git pull --ff-only

echo "Rebuilding and restarting containers..."
docker compose up -d --build

echo "Current container status:"
docker compose ps

if [ -f "${BACKUP_PATH}" ]; then
    echo "Backup saved to ${BACKUP_PATH}"
fi
