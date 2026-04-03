#!/usr/bin/env bash
# =============================================================================
#  AIDEN v2.0 — Start Script  (Linux / macOS)
#  Usage:  ./start.sh [--setup] [--docker] [--stop]
#
#  Flags:
#    --setup     Force reinstall of Python dependencies
#    --docker    Use Docker for MongoDB instead of a local mongod
#    --stop      Kill all AIDEN processes and exit
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[AIDEN]${RESET}  $*"; }
success() { echo -e "${GREEN}[✓]${RESET}     $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET}     $*"; }
error()   { echo -e "${RED}[✗]${RESET}     $*"; }
header()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════════${RESET}"; \
            echo -e "${BOLD}${CYAN}  $*${RESET}"; \
            echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${RESET}\n"; }

# ── Parse flags ───────────────────────────────────────────────────────────────
FORCE_SETUP=false
USE_DOCKER=false
DO_STOP=false

for arg in "$@"; do
  case $arg in
    --setup)  FORCE_SETUP=true ;;
    --docker) USE_DOCKER=true  ;;
    --stop)   DO_STOP=true     ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PID_DIR="$SCRIPT_DIR/.pids"
LOG_DIR="$SCRIPT_DIR/logs"
UI_PORT=3000
API_PORT=8000

# ── Stop mode ─────────────────────────────────────────────────────────────────
if $DO_STOP; then
  header "Stopping AIDEN"
  for pidfile in "$PID_DIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    name=$(basename "$pidfile" .pid)
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && success "Stopped $name (PID $pid)"
    else
      warn "$name (PID $pid) was already gone"
    fi
    rm -f "$pidfile"
  done
  if $USE_DOCKER; then
    info "Stopping Docker services..."
    docker compose -f "$SCRIPT_DIR/deploy/docker-compose.yml" down 2>/dev/null || true
  fi
  success "All AIDEN processes stopped."
  exit 0
fi

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat << 'EOF'
    ___    _________  _______   __
   /   |  /  _/ __ \/ ____/ | / /
  / /| |  / // / / / __/ /  |/ /
 / ___ |_/ // /_/ / /___/ /|  /
/_/  |_/___/_____/_____/_/ |_/

  v2.0 — AI Daily Executive Navigator
EOF
echo -e "${RESET}"

mkdir -p "$PID_DIR" "$LOG_DIR"

# ── 1. Prerequisites check ────────────────────────────────────────────────────
header "Checking Prerequisites"

# Python 3.11+
if ! command -v python3 &>/dev/null; then
  error "python3 not found. Install Python 3.11+ from https://python.org"
  exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  error "Python 3.11+ required (found $PY_VERSION)"
  exit 1
fi
success "Python $PY_VERSION"

# pip
if ! python3 -m pip --version &>/dev/null; then
  error "pip not found. Run: python3 -m ensurepip"
  exit 1
fi
success "pip available"

# Docker (optional)
if $USE_DOCKER; then
  if ! command -v docker &>/dev/null; then
    error "--docker flag set but Docker not found. Install from https://docker.com"
    exit 1
  fi
  success "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
fi

# curl / python http.server for UI
if command -v python3 &>/dev/null; then
  success "UI server: python3 -m http.server"
fi

# ── 2. Environment file ───────────────────────────────────────────────────────
header "Environment Configuration"

ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    warn ".env not found — copied from .env.example"
    warn "Please edit $ENV_FILE and add your GEMINI_API_KEY and JWT_SECRET, then re-run."
    echo ""
    echo -e "  ${YELLOW}Required values to fill in:${RESET}"
    echo -e "    GEMINI_API_KEY   — from https://aistudio.google.com/app/apikey"
    echo -e "    JWT_SECRET       — run: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
    echo ""
    read -rp "  Open .env in editor now? [y/N] " OPEN_ENV
    if [[ "${OPEN_ENV,,}" == "y" ]]; then
      "${EDITOR:-nano}" "$ENV_FILE"
    else
      error "Cannot start without a configured .env. Edit it and re-run."
      exit 1
    fi
fi
fi

# Validate critical keys
source_env() {
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}
source_env

if [ -z "${GEMINI_API_KEY:-}" ] || [ "$GEMINI_API_KEY" = "your_gemini_api_key_here" ]; then
  error "GEMINI_API_KEY is not set in .env"
  exit 1
fi
if [ -z "${JWT_SECRET:-}" ] || [ "$JWT_SECRET" = "your_jwt_secret_min_32_characters_required_here" ]; then
  error "JWT_SECRET is not set in .env (min 32 chars)"
  echo "  Generate one: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
  exit 1
fi
if [ ${#JWT_SECRET} -lt 32 ]; then
  error "JWT_SECRET is too short (${#JWT_SECRET} chars). Minimum 32 characters."
  exit 1
fi

success ".env loaded and validated"

# Derive ports from .env (with fallbacks)
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-3000}"

# ── 3. Python virtual environment ─────────────────────────────────────────────
header "Python Environment"

if [ ! -d "$VENV_DIR" ] || $FORCE_SETUP; then
  info "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
  success "Virtual environment created at .venv/"
fi

# Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
success "Virtual environment activated"

# Install / upgrade dependencies
if [ ! -f "$VENV_DIR/.installed" ] || $FORCE_SETUP; then
  info "Installing dependencies (this may take 1-2 minutes on first run)..."
  pip install --quiet --upgrade pip
  pip install --quiet -e "$SCRIPT_DIR"
  touch "$VENV_DIR/.installed"
  success "Dependencies installed"
else
  success "Dependencies already installed (use --setup to reinstall)"
fi

# ── 4. MongoDB ────────────────────────────────────────────────────────────────
header "Starting MongoDB"

MONGO_URI="${MONGO_URI:-mongodb://localhost:27017}"
MONGO_PORT=27017

if $USE_DOCKER; then
  info "Starting MongoDB via Docker Compose..."
  docker compose -f "$SCRIPT_DIR/deploy/docker-compose.yml" up -d mongo
  info "Waiting for MongoDB to be healthy..."
  for i in $(seq 1 20); do
    if docker exec aiden_mongo mongosh --eval "db.adminCommand('ping')" &>/dev/null 2>&1; then
      success "MongoDB is ready (Docker)"
      break
    fi
    sleep 2
    if [ "$i" -eq 20 ]; then
      error "MongoDB did not become healthy in time."
      exit 1
    fi
  done
else
  # Try local mongod
  if command -v mongod &>/dev/null; then
    if ! mongosh --eval "db.adminCommand('ping')" --quiet &>/dev/null 2>&1; then
      info "Starting local mongod..."
      mkdir -p "$SCRIPT_DIR/data/mongodb"
      mongod --dbpath "$SCRIPT_DIR/data/mongodb" \
             --port $MONGO_PORT \
             --logpath "$LOG_DIR/mongodb.log" \
             --fork \
             --quiet
      sleep 2
      success "Local mongod started"
    else
      success "MongoDB already running locally"
    fi
  else
    warn "mongod not found locally. Options:"
    warn "  1. Run with --docker flag to use Docker"
    warn "  2. Install MongoDB: https://www.mongodb.com/docs/manual/installation/"
    error "Cannot start without MongoDB."
    exit 1
  fi
fi

# ── 5. ChromaDB data directory ────────────────────────────────────────────────
CHROMA_PATH="${CHROMA_PATH:-./data/chroma}"
mkdir -p "$SCRIPT_DIR/data/chroma"
success "ChromaDB data directory: $CHROMA_PATH"

# ── 6. FastAPI backend ────────────────────────────────────────────────────────
header "Starting FastAPI Backend"

API_PIDFILE="$PID_DIR/api.pid"
API_LOG="$LOG_DIR/api.log"

# Kill any stale process
if [ -f "$API_PIDFILE" ]; then
  OLD_PID=$(cat "$API_PIDFILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    info "Restarting existing API process (PID $OLD_PID)..."
    kill "$OLD_PID"
    sleep 1
  fi
  rm -f "$API_PIDFILE"
fi

cd "$SCRIPT_DIR"

uvicorn src.api.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "$API_PORT" \
  --workers "${API_WORKERS:-1}" \
  --log-level info \
  > "$API_LOG" 2>&1 &

API_PID=$!
echo "$API_PID" > "$API_PIDFILE"

# Wait for API to be ready
info "Waiting for API to be ready..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$API_PORT/health" &>/dev/null; then
    success "FastAPI backend running  →  http://localhost:$API_PORT"
    success "API docs                →  http://localhost:$API_PORT/docs"
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    error "API did not start in time. Check logs: $API_LOG"
    error "Last 20 lines:"
    tail -20 "$API_LOG"
    exit 1
  fi
done

# ── 7. React UI (static file server) ─────────────────────────────────────────
header "Starting UI"

UI_PIDFILE="$PID_DIR/ui.pid"
UI_LOG="$LOG_DIR/ui.log"

if [ -f "$UI_PIDFILE" ]; then
  OLD_PID=$(cat "$UI_PIDFILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID"
    sleep 1
  fi
  rm -f "$UI_PIDFILE"
fi

cd "$SCRIPT_DIR/ui_react"

python3 -m http.server "$UI_PORT" \
  > "$UI_LOG" 2>&1 &

UI_PID=$!
echo "$UI_PID" > "$UI_PIDFILE"
cd "$SCRIPT_DIR"

sleep 1
if kill -0 "$UI_PID" 2>/dev/null; then
  success "UI server running  →  http://localhost:$UI_PORT"
else
  error "UI server failed to start. Check: $UI_LOG"
fi

# ── 8. Open browser ───────────────────────────────────────────────────────────
sleep 1
UI_URL="http://localhost:$UI_PORT"
info "Opening browser at $UI_URL ..."

if command -v open &>/dev/null; then          # macOS
  open "$UI_URL"
elif command -v xdg-open &>/dev/null; then    # Linux
  xdg-open "$UI_URL" &>/dev/null &
elif command -v wslview &>/dev/null; then     # WSL2
  wslview "$UI_URL"
fi

# ── 9. Summary ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  AIDEN v2.0 is running!${RESET}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${CYAN}UI${RESET}        http://localhost:$UI_PORT"
echo -e "  ${CYAN}API${RESET}       http://localhost:$API_PORT"
echo -e "  ${CYAN}API Docs${RESET}  http://localhost:$API_PORT/docs"
echo -e "  ${CYAN}API Log${RESET}   $API_LOG"
echo -e "  ${CYAN}UI Log${RESET}    $UI_LOG"
echo ""
echo -e "  Press ${BOLD}Ctrl+C${RESET} to stop all services."
echo ""

# ── 10. Wait & cleanup on Ctrl+C ─────────────────────────────────────────────
cleanup() {
  echo ""
  header "Shutting Down AIDEN"
  for pidfile in "$PID_DIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    name=$(basename "$pidfile" .pid)
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      success "Stopped $name (PID $pid)"
    fi
    rm -f "$pidfile"
  done
  if $USE_DOCKER; then
    info "Stopping Docker services..."
    docker compose -f "$SCRIPT_DIR/deploy/docker-compose.yml" down 2>/dev/null || true
  fi
  success "Goodbye."
  exit 0
}

trap cleanup INT TERM

# Keep script alive and tail API logs
tail -f "$API_LOG" &
wait
