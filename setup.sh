set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[AIDEN]${RESET}  $*"; }
success() { echo -e "${GREEN}[✓]${RESET}     $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET}     $*"; }
error()   { echo -e "${RED}[✗]${RESET}     $*" >&2; exit 1; }
ask()     { echo -e "${YELLOW}[?]${RESET}     $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

clear
echo -e "${BOLD}${CYAN}"
echo "  AIDEN v2.0 — First-time Setup"
echo "  ─────────────────────────────"
echo -e "${RESET}"

# ── Python check ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then error "python3 not found. Install Python 3.11+."; fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python $PY_VER detected"

# ── Create .env ───────────────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  warn ".env already exists. Skipping creation."
else
  # Generate a secure JWT secret automatically
  JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

  echo ""
  ask "Enter your Gemini API key (get one at https://aistudio.google.com/app/apikey):"
  read -r GEMINI_KEY

  if [ -z "$GEMINI_KEY" ]; then
    error "Gemini API key cannot be empty."
  fi

  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"

  # Substitute placeholders
  sed -i.bak \
    -e "s|your_gemini_api_key_here|$GEMINI_KEY|" \
    -e "s|your_jwt_secret_min_32_characters_required_here|$JWT_SECRET|" \
    "$ENV_FILE"
  rm -f "$ENV_FILE.bak"

  success ".env created with your Gemini key and a generated JWT secret"
  echo ""
  info  "Generated JWT_SECRET: ${BOLD}${JWT_SECRET}${RESET}"
  info  "Keep this secret safe — it signs all user sessions."
fi

# ── Virtual environment ───────────────────────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  info "Creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
  success "Virtual environment created at .venv/"
fi

source "$VENV_DIR/bin/activate"
info "Installing Python dependencies (may take 1-2 minutes)..."
pip install --quiet --upgrade pip
pip install --quiet -e "$SCRIPT_DIR"
touch "$VENV_DIR/.installed"
success "All dependencies installed"

# ── Data directories ──────────────────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/data/chroma"
mkdir -p "$SCRIPT_DIR/data/mongodb"
mkdir -p "$SCRIPT_DIR/logs"
success "Data directories created"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Setup complete!${RESET}"
echo ""
echo -e "  ${CYAN}Next steps:${RESET}"
echo -e "  1. Review your .env file:  ${BOLD}cat .env${RESET}"
echo -e "  2. Start AIDEN:            ${BOLD}./start.sh${RESET}            (local MongoDB)"
echo -e "                             ${BOLD}./start.sh --docker${RESET}   (Docker MongoDB)"
echo ""
echo -e "  ${YELLOW}Optional:${RESET} Add Gmail OAuth credentials to .env to enable Gmail integration."
echo -e "  See: https://console.cloud.google.com/apis/credentials"
echo ""
