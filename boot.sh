#!/usr/bin/env bash
set -euo pipefail

# Boot script: start Redis locally, then start the API server.
# This keeps the container self-contained (no docker-compose required).

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DIR="${REDIS_DIR:-/app/redis-data}"

# Optional: override Redis startup args
# Example: REDIS_ARGS="--appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru"
REDIS_ARGS="${REDIS_ARGS:-}"

mkdir -p "${REDIS_DIR}"

echo "Starting redis-server on ${REDIS_HOST}:${REDIS_PORT} (dir=${REDIS_DIR})..."
redis-server \
  --bind "${REDIS_HOST}" \
  --port "${REDIS_PORT}" \
  --dir "${REDIS_DIR}" \
  --protected-mode yes \
  --save "" \
  --appendonly no \
  ${REDIS_ARGS} \
  >/dev/stdout 2>/dev/stderr &

REDIS_PID="$!"

cleanup() {
  echo "Shutting down redis-server (pid=${REDIS_PID})..."
  kill "${REDIS_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Waiting for Redis to be ready..."
for _ in $(seq 1 50); do
  if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping >/dev/null 2>&1; then
    echo "Redis is ready."
    break
  fi
  sleep 0.1
done

if ! redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping >/dev/null 2>&1; then
  echo "Redis failed to start."
  exit 1
fi

# Ensure the app points at the in-container Redis by default
export REDIS_URL="${REDIS_URL:-redis://${REDIS_HOST}:${REDIS_PORT}/0}"

echo "Starting API (gunicorn)..."
exec /app/launch_gunicorn.sh


