#!/bin/bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
TICK="${GREEN}✓${RESET}"; CROSS="${RED}✗${RESET}"; ARROW="${CYAN}▶${RESET}"

banner() {
  echo ""
  echo -e "${BOLD}${BLUE}╔══════════════════════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}${BLUE}  $1${RESET}"
  echo -e "${BOLD}${BLUE}╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo ""
}

step_header() {
  echo ""
  echo -e "${BOLD}${CYAN}━━━ $1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${YELLOW}$2${RESET}"
  echo ""
}

ask() {
  while true; do
    printf "${BOLD}${1} [Y/n]: ${RESET}"
    read -r ans
    case "${ans,,}" in y|yes|"") return 0;; n|no) return 1;; esac
  done
}

ok()   { echo -e "${TICK} $1"; }
warn() { echo -e "${YELLOW}⚠  $1${RESET}"; }
err()  { echo -e "${CROSS} ${RED}$1${RESET}"; }

# ═════════════════════════════════════════════════════════════════════════════
banner "AIDEN v3.1 — Prerequisites Setup"
# ═════════════════════════════════════════════════════════════════════════════
echo "This script checks and installs all prerequisites for deploying AIDEN."
echo "Run it once before deploy.sh."
echo ""

OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then OS="macos"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then OS="linux"
else
  warn "Windows detected. Use WSL2 (Ubuntu) or Git Bash to run these scripts."
  warn "Alternatively run deploy.sh from Cloud Shell: https://shell.cloud.google.com"
  exit 1
fi
ok "OS detected: $OS"

# ─────────────────────────────────────────────────────────────────────────────
step_header "1. Check gcloud CLI" \
  "The Google Cloud CLI (gcloud) is required to deploy to Cloud Run."

GCLOUD_AVAILABLE=false
if command -v gcloud &>/dev/null; then
  GCLOUD_VER=$(gcloud version 2>/dev/null | head -1 | sed 's/Google Cloud SDK //')
  ok "gcloud already installed: ${GCLOUD_VER}"
  GCLOUD_AVAILABLE=true
else
  warn "gcloud CLI not found."
  echo ""
  echo -e "Install instructions:"
  if [[ "$OS" == "macos" ]]; then
    echo -e "  ${CYAN}brew install --cask google-cloud-sdk${RESET}"
    echo -e "  OR download from: https://cloud.google.com/sdk/docs/install"
    if ask "Install gcloud via Homebrew now?"; then
      if ! command -v brew &>/dev/null; then
        err "Homebrew not found. Install from https://brew.sh first."
        exit 1
      fi
      brew install --cask google-cloud-sdk
      ok "gcloud installed via Homebrew."
      GCLOUD_AVAILABLE=true
    fi
  else
    echo -e "  ${CYAN}curl https://sdk.cloud.google.com | bash${RESET}"
    echo -e "  Then restart your shell."
    if ask "Run the gcloud installer now?"; then
      curl https://sdk.cloud.google.com | bash
      # Re-source the shell profile so gcloud is on PATH
      for f in "$HOME/.bashrc" "$HOME/.profile" "$HOME/.bash_profile"; do
        [[ -f "$f" ]] && source "$f" 2>/dev/null || true
      done
      if command -v gcloud &>/dev/null; then
        ok "gcloud installed successfully."
        GCLOUD_AVAILABLE=true
      else
        warn "gcloud installed but not on PATH yet. Restart your terminal and re-run this script."
      fi
    fi
  fi
fi

if [[ "$GCLOUD_AVAILABLE" != "true" ]]; then
  warn "gcloud is required for steps 2–6. Install it and re-run this script."
  echo ""
  echo -e "  Linux:  ${CYAN}curl https://sdk.cloud.google.com | bash${RESET}"
  echo -e "  macOS:  ${CYAN}brew install --cask google-cloud-sdk${RESET}"
  echo -e "  Or use Cloud Shell: ${CYAN}https://shell.cloud.google.com${RESET}"
  echo ""
  # Still continue to Docker check (step 5) and MongoDB (step 7)
fi

# ─────────────────────────────────────────────────────────────────────────────
if [[ "$GCLOUD_AVAILABLE" == "true" ]]; then

step_header "2. gcloud Authentication" \
  "Log in to your Google account so gcloud can act on your behalf."

CURRENT_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1 || echo "")
if [[ -n "$CURRENT_ACCOUNT" ]]; then
  ok "Already authenticated as: ${CYAN}${CURRENT_ACCOUNT}${RESET}"
  if ask "Re-authenticate with a different account?"; then
    gcloud auth login
  fi
else
  warn "Not authenticated."
  if ask "Run 'gcloud auth login' to authenticate?"; then
    gcloud auth login
    ok "Authentication complete."
  else
    warn "Skipped. Run 'gcloud auth login' before deploy.sh."
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step_header "3. Application Default Credentials" \
  "ADC lets Google client libraries (Vertex AI, Secret Manager) authenticate
  automatically without manual token management."

ADC_FILE="$HOME/.config/gcloud/application_default_credentials.json"
if [[ -f "$ADC_FILE" ]]; then
  ok "Application Default Credentials already set."
else
  warn "ADC not configured."
  if ask "Run 'gcloud auth application-default login'?"; then
    gcloud auth application-default login
    ok "ADC configured."
  else
    warn "Skipped. Run 'gcloud auth application-default login' before deploying."
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step_header "4. Set / Create GCP Project" \
  "Every GCP resource (Cloud Run, Artifact Registry, etc.) lives in a project.
  You can use an existing project or create a new one."

CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
echo -e "Current project: ${CYAN}${CURRENT_PROJECT:-none}${RESET}"
echo ""

if ask "Set up a GCP project now?"; then
  echo ""
  echo -e "Options:"
  echo -e "  1) Use existing project"
  echo -e "  2) Create a new project"
  echo ""
  printf "${BOLD}Choose [1/2]: ${RESET}"
  read -r choice

  if [[ "$choice" == "2" ]]; then
    printf "${BOLD}New project ID (lowercase, hyphens only, max 30 chars): ${RESET}"
    read -r NEW_PROJECT_ID
    printf "${BOLD}Project display name: ${RESET}"
    read -r PROJECT_NAME

    echo -e "${ARROW} Creating project '${NEW_PROJECT_ID}'..."
    gcloud projects create "$NEW_PROJECT_ID" --name="$PROJECT_NAME" 2>/dev/null || \
      warn "Project may already exist — continuing."

    echo ""
    warn "IMPORTANT: You must enable billing for the project before APIs can be used."
    echo -e "  Open: ${CYAN}https://console.cloud.google.com/billing/linkedaccount?project=${NEW_PROJECT_ID}${RESET}"
    echo ""
    read -rp "Press Enter once billing is enabled..."

    gcloud config set project "$NEW_PROJECT_ID" --quiet
    ok "Active project set to: ${NEW_PROJECT_ID}"
  else
    echo -e "${ARROW} Listing your projects:"
    gcloud projects list --format='table(projectId,name,projectNumber)' 2>/dev/null | head -20
    echo ""
    printf "${BOLD}Enter project ID to use: ${RESET}"
    read -r EXISTING_PROJECT
    gcloud config set project "$EXISTING_PROJECT" --quiet
    ok "Active project set to: ${EXISTING_PROJECT}"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step_header "5. Check Docker" \
  "Docker is required to build container images locally if not using Cloud Build."

if command -v docker &>/dev/null; then
  if docker info &>/dev/null 2>&1; then
    DOCKER_VER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
    ok "Docker running: v${DOCKER_VER}"
  else
    warn "Docker installed but daemon not running."
    echo "  Start Docker Desktop (macOS/Windows) or run: sudo systemctl start docker (Linux)"
  fi
else
  warn "Docker not found."
  echo -e "  Install from: ${CYAN}https://docs.docker.com/get-docker/${RESET}"
  if [[ "$OS" == "macos" ]]; then
    echo -e "  Or: ${CYAN}brew install --cask docker${RESET}"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step_header "6. Install gcloud Components" \
  "Installs the beta component (needed for multi-container Cloud Run) and
  the cloud-run-proxy component."

if ask "Install/update required gcloud components?"; then
  gcloud components install beta --quiet 2>/dev/null || \
    warn "Could not install beta component (may need sudo or managed install)."
  ok "gcloud components updated."
fi

fi  # end of GCLOUD_AVAILABLE block

# ─────────────────────────────────────────────────────────────────────────────
step_header "7. Verify MongoDB Atlas Connectivity" \
  "Checks that your Atlas cluster is accessible from this machine.
  (This does NOT test from Cloud Run — Atlas must allow 0.0.0.0/0 or Cloud Run IPs.)"

echo -e "${YELLOW}IMPORTANT:${RESET} In MongoDB Atlas console, go to:"
echo -e "  Network Access → Add IP Address → Allow Access from Anywhere (0.0.0.0/0)"
echo -e "  This is required for Cloud Run (dynamic IPs) to connect."
echo ""
if ask "Open MongoDB Atlas Network Access page in browser?"; then
  URL="https://cloud.mongodb.com"
  if [[ "$OS" == "macos" ]]; then open "$URL"
  else xdg-open "$URL" 2>/dev/null || echo "Open: $URL"; fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# FINAL STATUS
# ─────────────────────────────────────────────────────────────────────────────
banner "Prerequisites Check Complete"

if [[ "$GCLOUD_AVAILABLE" == "true" ]]; then
  ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1 || echo "NOT SET")
  ACTIVE_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "NOT SET")

  echo -e "${BOLD}Current gcloud state:${RESET}"
  echo -e "  ${TICK} Authenticated as: ${CYAN}${ACTIVE_ACCOUNT}${RESET}"
  echo -e "  ${TICK} Active project:   ${CYAN}${ACTIVE_PROJECT}${RESET}"
else
  warn "gcloud not available — install it and re-run this script."
fi
echo ""
echo -e "${BOLD}Ready to deploy?${RESET}"
echo -e "  Run: ${CYAN}./deploy.sh${RESET}"
echo ""
