#!/bin/bash

# Calculate workers: CPU cores + 1
if command -v nproc >/dev/null 2>&1; then
    CPU_CORES=$(nproc)
elif command -v sysctl >/dev/null 2>&1; then
    CPU_CORES=$(sysctl -n hw.ncpu)
else
    CPU_CORES=4
fi
WORKERS=$((CPU_CORES + 1))

echo "CPU cores: $CPU_CORES, Using workers: $WORKERS"

gunicorn atp.api:app \
  --bind 0.0.0.0:8000 \
  --workers $WORKERS \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 600 \
  --keep-alive 65 \
  --log-level info \
  --preload

