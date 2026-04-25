#!/usr/bin/env bash
# 本地开发环境一键启动（Docker 模式）。
#
# 用法:
#   ./dev.sh           # 前台启动，Ctrl+C 停止
#   ./dev.sh -d        # 后台启动
#   ./dev.sh down      # 停止并移除容器
#   ./dev.sh logs      # 跟看日志
#   ./dev.sh rebuild   # 强制重新构建镜像后启动

set -euo pipefail
cd "$(dirname "$0")"

# --- 前置检查 ---
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ docker 未安装"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "❌ docker compose 不可用（需 Docker Compose v2+）"
  exit 1
fi

if [ ! -f .env ]; then
  echo "❌ .env 不存在，先 cp .env.example .env 并填入 MOONSHOT_API_KEY"
  exit 1
fi

if grep -qE '^MOONSHOT_API_KEY=sk-xxxxxxxxx$' .env; then
  echo "❌ .env 里的 MOONSHOT_API_KEY 还是占位符，请填入真实 key"
  exit 1
fi

# --- 子命令分发 ---
case "${1:-up}" in
  down)
    docker compose down
    ;;
  logs)
    docker compose logs -f --tail=200
    ;;
  rebuild)
    docker compose build --no-cache
    docker compose up
    ;;
  -d|up-d)
    docker compose up -d
    echo "✅ 已后台启动. 前端 http://localhost:3000 · 后端 http://localhost:8000"
    echo "   查看日志: ./dev.sh logs"
    ;;
  up|"")
    echo "🚀 启动 docker compose（首次约 5-10 分钟，需下载 BGE 模型 ~1GB）..."
    echo "   前端 http://localhost:3000 · 后端 http://localhost:8000"
    docker compose up
    ;;
  *)
    echo "未知子命令: $1"
    echo "用法: ./dev.sh [up|-d|down|logs|rebuild]"
    exit 2
    ;;
esac
