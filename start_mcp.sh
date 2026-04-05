
set -euo pipefail

DEV_MODE=false
STOP_MODE=false

for arg in "$@"; do
  case $arg in
    --dev)  DEV_MODE=true ;;
    --stop) STOP_MODE=true ;;
  esac
done

COMPOSE_FILE="deploy/docker-compose.yml"

if [ "$STOP_MODE" = true ]; then
  echo "Stopping all AIDEN MCP servers..."
  docker compose -f "$COMPOSE_FILE" down workspace-mcp mongodb-mcp notion-mcp github-mcp 2>/dev/null || true
  echo "MCP servers stopped."
  exit 0
fi

echo "Starting AIDEN v3.0 MCP servers..."

# Always start: workspace, mongodb, notion
docker compose -f "$COMPOSE_FILE" up -d workspace-mcp mongodb-mcp notion-mcp

if [ "$DEV_MODE" = true ]; then
  echo "  [dev] Starting GitHub MCP..."
  docker compose -f "$COMPOSE_FILE" --profile dev up -d github-mcp
fi

echo ""
echo "MCP servers starting:"
echo "  Port 8001 — Google Workspace MCP (Calendar, Gmail, Drive, Docs)"
echo "  Port 8002 — MongoDB MCP (read-only queries)"
echo "  Port 8003 — Notion MCP (team knowledge)"
if [ "$DEV_MODE" = true ]; then
echo "  Port 8004 — GitHub MCP (developer mode)"
fi
echo ""
echo "Check status: docker compose -f $COMPOSE_FILE ps"
echo "View logs:    docker compose -f $COMPOSE_FILE logs -f workspace-mcp"
