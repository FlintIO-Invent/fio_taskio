#!/usr/bin/env bash
set -o errexit

cd "$(dirname "$0")"

uv sync --locked

uv run --no-sync python src/manage.py collectstatic --no-input
uv run --no-sync python src/manage.py migrate
