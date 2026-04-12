#!/usr/bin/env bash
set -o errexit

cd "$(dirname "$0")"

uv run --frozen python -m gunicorn taskio.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --chdir src \
  --bind "0.0.0.0:${PORT:-8000}"
