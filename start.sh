#!/usr/bin/env bash
set -o errexit

cd "$(dirname "$0")"

uv run --frozen gunicorn taskio.wsgi:application \
  --chdir src \
  --log-file - \
  --bind "0.0.0.0:${PORT:-8000}"
