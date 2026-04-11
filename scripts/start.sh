#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> TestFlow AI — local dev startup"

# Check .env
if [ ! -f "$ROOT/.env" ]; then
  echo "  [!] .env not found. Copying from .env.example..."
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "  [!] Edit .env and add your ANTHROPIC_API_KEY, then re-run."
  exit 1
fi

echo "==> Starting PostgreSQL via Docker..."
docker compose -f "$ROOT/docker-compose.yml" up -d db

echo "==> Waiting for PostgreSQL..."
until docker compose -f "$ROOT/docker-compose.yml" exec -T db pg_isready -U testflow; do
  sleep 1
done

echo "==> Installing backend dependencies..."
cd "$ROOT/backend"
pip install -r requirements.txt -q

echo "==> Starting FastAPI backend..."
PYTHONPATH="$ROOT" uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "==> Installing frontend dependencies..."
cd "$ROOT/frontend"
npm install --silent

echo "==> Starting Vite frontend..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop all services."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; docker compose -f '$ROOT/docker-compose.yml' stop db" EXIT
wait
