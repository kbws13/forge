#!/usr/bin/env bash
# 启动脚本：APP_ENV=dev|prod|test
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-dev}"
PORT="${PORT:-8000}"
if [ "$APP_ENV" = "dev" ]; then
  exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
else
  exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi
