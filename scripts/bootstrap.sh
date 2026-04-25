#!/usr/bin/env bash
# One-shot host-mode local setup (alternative to `docker compose up`):
# 0. ensure .venv exists and dependencies installed (via uv)
# 1. start ONLY the postgres container (backend runs on host)
# 2. source .env so APP_USER_ID and other vars are visible to subprocesses
# 3. run alembic migrations
# 4. seed demo user (idempotent; uses APP_USER_ID from .env)
# 5. print remaining manual setup (MOONSHOT_API_KEY) + how to start the API

set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "🐍 Creating venv with uv..."
  uv venv --python 3.11
fi

echo "📦 Installing deps..."
uv pip install -e ".[dev]"

# 接下来的 python / alembic 命令都需要 venv 里的解释器
source .venv/bin/activate

if [ ! -f .env ]; then
  echo "Creating .env from .env.example"
  cp .env.example .env
fi

# Load .env into shell so seed_demo_user.py + alembic see APP_USER_ID
set -a
. .env
set +a

echo "🐳 Starting Postgres..."
docker compose up -d postgres

echo "⏳ Waiting for postgres to be ready..."
for i in {1..20}; do
  if docker compose exec -T postgres pg_isready -U postgres -d chat >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "📦 Running migrations..."
alembic upgrade head

echo "🌱 Seeding demo user..."
python scripts/seed_demo_user.py

echo ""
echo "✅ Bootstrap complete. Demo user ready as APP_USER_ID=$APP_USER_ID"
echo ""
echo "Remaining manual step:"
echo "  • Put MOONSHOT_API_KEY in .env (currently the placeholder fails real LLM calls)"
echo ""
echo "Then start the API:  uvicorn --factory src.main:make_app_default --reload"
echo ""
echo "Or skip host-mode entirely and run:  docker compose up"
