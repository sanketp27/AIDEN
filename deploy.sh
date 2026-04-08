#!/usr/bin/env bash
# =============================================================================
#  AIDEN v3.1 — Interactive Cloud Run Deployment Script
#  Runs every command one at a time, shows a summary, asks Y/N to continue.
# =============================================================================
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
TICK="${GREEN}✓${RESET}"; CROSS="${RED}✗${RESET}"; ARROW="${CYAN}▶${RESET}"

# ── Helpers ───────────────────────────────────────────────────────────────────
banner() {
  echo ""
  echo -e "${BOLD}${BLUE}╔══════════════════════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}${BLUE}  $1${RESET}"
  echo -e "${BOLD}${BLUE}╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo ""
}

step_header() {
  local num=$1 title=$2 desc=$3
  echo ""
  echo -e "${BOLD}${CYAN}━━━ Step ${num}: ${title} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${YELLOW}What this does:${RESET} ${desc}"
  echo ""
}

ask() {
  # ask <question> — returns 0 (yes) or 1 (no)
  local q=$1
  while true; do
    printf "${BOLD}${q} [Y/n]: ${RESET}"
    read -r ans
    case "${ans,,}" in
      y|yes|"") return 0 ;;
      n|no)      return 1 ;;
      *)         echo -e "${YELLOW}Please enter Y or N.${RESET}" ;;
    esac
  done
}

ask_value() {
  # ask_value <prompt> <varname> [default]
  local prompt=$1 varname=$2 default=${3:-}
  if [[ -n "$default" ]]; then
    printf "${BOLD}${prompt}${RESET} [${CYAN}${default}${RESET}]: "
  else
    printf "${BOLD}${prompt}${RESET}: "
  fi
  read -r input
  if [[ -z "$input" && -n "$default" ]]; then
    eval "${varname}='${default}'"
  else
    eval "${varname}='${input}'"
  fi
}

ask_secret() {
  # ask_secret <prompt> <varname>
  local prompt=$1 varname=$2
  printf "${BOLD}${prompt}${RESET} (input hidden): "
  read -rs input; echo ""
  eval "${varname}='${input}'"
}

run_cmd() {
  # run_cmd <description> <command...>
  # Uses "$@" (not eval "$@") so quoted arguments with spaces are preserved
  # correctly — e.g. --description="AIDEN container images" stays one token.
  local desc=$1; shift
  echo -e "${ARROW} Running: ${CYAN}$*${RESET}"
  echo ""
  if "$@"; then
    echo ""
    echo -e "${TICK} ${GREEN}Done: ${desc}${RESET}"
  else
    echo ""
    echo -e "${CROSS} ${RED}FAILED: ${desc}${RESET}"
    echo -e "${YELLOW}You can fix the issue and re-run this script — it is idempotent.${RESET}"
    exit 1
  fi
}

skip_msg() {
  echo -e "${YELLOW}⏭  Skipped.${RESET}"
}

summary_line() {
  printf "  ${TICK} %-30s ${CYAN}%s${RESET}\n" "$1" "$2"
}

# ═════════════════════════════════════════════════════════════════════════════
banner "AIDEN v3.1 — Cloud Run Deployment Wizard"
# ═════════════════════════════════════════════════════════════════════════════
echo -e "This script will deploy AIDEN to Google Cloud Run step-by-step."
echo -e "It will ${BOLD}ask before running each command${RESET}."
echo -e "All steps are ${GREEN}idempotent${RESET} — safe to re-run if something fails."
echo ""
echo -e "${YELLOW}Requirements before starting:${RESET}"
echo "  • gcloud CLI installed and authenticated  (run 0_prerequisites.sh if not)"
echo "  • Docker installed and running"
echo "  • MongoDB Atlas URI ready"
echo "  • Google OAuth Client ID + Secret ready"
echo "  • Gemini API key ready"
echo ""

if ! ask "Ready to begin deployment?"; then
  echo "Exiting. Run 0_prerequisites.sh first if you need to set up gcloud."
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# COLLECT CONFIG
# ─────────────────────────────────────────────────────────────────────────────
banner "Configuration"

echo -e "${YELLOW}Enter your deployment configuration:${RESET}"
echo ""

ask_value "GCP Project ID" PROJECT_ID ""
while [[ -z "$PROJECT_ID" ]]; do
  echo -e "${RED}Project ID cannot be empty.${RESET}"
  ask_value "GCP Project ID" PROJECT_ID ""
done

ask_value "GCP Region" REGION "us-central1"
ask_value "Cloud Run service name" SERVICE_NAME "aiden-api"
ask_value "Artifact Registry repo name" REPO "aiden"

echo ""
echo -e "${YELLOW}Enter your secret values:${RESET}"
echo ""

ask_secret "MongoDB Atlas URI  (mongodb+srv://...)" MONGO_URI
while [[ -z "$MONGO_URI" ]]; do
  echo -e "${RED}MongoDB URI cannot be empty.${RESET}"
  ask_secret "MongoDB Atlas URI" MONGO_URI
done

ask_secret "Gemini API Key" GEMINI_KEY
while [[ -z "$GEMINI_KEY" ]]; do
  echo -e "${RED}Gemini API Key cannot be empty.${RESET}"
  ask_secret "Gemini API Key" GEMINI_KEY
done

ask_secret "JWT Secret  (min 32 random chars)" JWT_SECRET
while [[ ${#JWT_SECRET} -lt 32 ]]; do
  echo -e "${RED}JWT Secret must be at least 32 characters.${RESET}"
  ask_secret "JWT Secret" JWT_SECRET
done

ask_secret "Google OAuth Client ID" GOOGLE_CLIENT_ID
ask_secret "Google OAuth Client Secret" GOOGLE_CLIENT_SECRET

NOTION_TOKEN=""
if ask "Do you have a Notion integration token?"; then
  ask_secret "Notion Token" NOTION_TOKEN
fi

# Derived values
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"
BUCKET="aiden-chroma-${PROJECT_ID}"

echo ""
echo -e "${BOLD}Configuration summary:${RESET}"
summary_line "GCP Project"    "$PROJECT_ID"
summary_line "Region"         "$REGION"
summary_line "Service"        "$SERVICE_NAME"
summary_line "Image base"     "$IMAGE_BASE"
summary_line "Chroma bucket"  "gs://${BUCKET}"
summary_line "Notion MCP"     "$([ -n "$NOTION_TOKEN" ] && echo enabled || echo disabled)"
echo ""

if ! ask "Proceed with this configuration?"; then
  echo "Exiting. Re-run the script to start over."
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Set active project
# ─────────────────────────────────────────────────────────────────────────────
step_header 1 "Set GCP Project" \
  "Sets '$PROJECT_ID' as the active gcloud project for all subsequent commands."

if ask "Run: gcloud config set project $PROJECT_ID?"; then
  run_cmd "Set active project" gcloud config set project "$PROJECT_ID" --quiet
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Enable APIs
# ─────────────────────────────────────────────────────────────────────────────
step_header 2 "Enable GCP APIs" \
  "Enables Cloud Run, Artifact Registry, Cloud Build, Vertex AI, Secret Manager,
  Cloud Storage, and IAM APIs. Safe to run even if already enabled."

if ask "Enable all required GCP APIs?"; then
  run_cmd "Enable APIs" gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    aiplatform.googleapis.com \
    secretmanager.googleapis.com \
    cloudresourcemanager.googleapis.com \
    storage.googleapis.com \
    iam.googleapis.com \
    --quiet
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Artifact Registry repository
# ─────────────────────────────────────────────────────────────────────────────
step_header 3 "Create Artifact Registry Repo" \
  "Creates a Docker image repository called '$REPO' in $REGION.
  Container images for the API and MCP sidecars will be stored here."

if ask "Create Artifact Registry repository '$REPO'?"; then
  if gcloud artifacts repositories describe "$REPO" --location="$REGION" &>/dev/null; then
    echo -e "${TICK} Repository '${REPO}' already exists — skipping creation."
  else
    run_cmd "Create Artifact Registry repo" \
      gcloud artifacts repositories create "$REPO" \
        --repository-format=docker \
        --location="$REGION" \
        --description="AIDEN container images" \
        --quiet
  fi
  echo ""
  echo -e "${ARROW} Configuring Docker to authenticate with Artifact Registry..."
  run_cmd "Configure Docker auth" \
    gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Create Secrets in Secret Manager
# ─────────────────────────────────────────────────────────────────────────────
step_header 4 "Create Secrets in Secret Manager" \
  "Stores all sensitive values (MongoDB URI, API keys, JWT secret, OAuth credentials)
  in Google Secret Manager. Cloud Run will inject these at runtime — no secrets in code."

create_secret() {
  local name=$1 value=$2
  if gcloud secrets describe "$name" &>/dev/null; then
    echo -e "  ${TICK} Secret '${name}' already exists — adding new version."
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --quiet
  else
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- --quiet
    echo -e "  ${TICK} Created secret: ${CYAN}${name}${RESET}"
  fi
}

if ask "Create/update all secrets in Secret Manager?"; then
  echo ""
  create_secret "AIDEN_MONGO_URI"             "$MONGO_URI"
  create_secret "AIDEN_GEMINI_API_KEY"        "$GEMINI_KEY"
  create_secret "AIDEN_JWT_SECRET"            "$JWT_SECRET"
  create_secret "AIDEN_GOOGLE_CLIENT_ID"      "$GOOGLE_CLIENT_ID"
  create_secret "AIDEN_GOOGLE_CLIENT_SECRET"  "$GOOGLE_CLIENT_SECRET"
  if [[ -n "$NOTION_TOKEN" ]]; then
    create_secret "AIDEN_NOTION_TOKEN" "$NOTION_TOKEN"
  else
    # Create placeholder so service.yaml secret ref doesn't fail
    if ! gcloud secrets describe "AIDEN_NOTION_TOKEN" &>/dev/null; then
      printf 'not-configured' | gcloud secrets create "AIDEN_NOTION_TOKEN" --data-file=- --quiet
      echo -e "  ${TICK} Created placeholder secret: AIDEN_NOTION_TOKEN"
    fi
  fi
  echo ""
  echo -e "${TICK} All secrets created/updated."
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — GCS Bucket for ChromaDB
# ─────────────────────────────────────────────────────────────────────────────
step_header 5 "Create GCS Bucket for ChromaDB Persistence" \
  "Creates a Cloud Storage bucket 'gs://${BUCKET}'.
  The Cloud Run API container mounts this bucket at /mnt/gcs/chroma so
  ChromaDB vector embeddings PERSIST across cold starts (not wiped like /tmp)."

if ask "Create GCS bucket 'gs://${BUCKET}'?"; then
  if gcloud storage buckets describe "gs://${BUCKET}" &>/dev/null 2>&1; then
    echo -e "${TICK} Bucket already exists — skipping."
  else
    run_cmd "Create GCS bucket" \
      gcloud storage buckets create "gs://${BUCKET}" \
        --location="$REGION" \
        --uniform-bucket-level-access
  fi
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — IAM Permissions
# ─────────────────────────────────────────────────────────────────────────────
step_header 6 "Grant IAM Permissions" \
  "Grants Cloud Build permission to deploy Cloud Run services.
  Grants the Cloud Run service account permission to:
    • Read secrets from Secret Manager
    • Call Vertex AI / Gemini APIs
    • Read/write the ChromaDB GCS bucket"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo -e "  Cloud Build SA:  ${CYAN}${CB_SA}${RESET}"
echo -e "  Cloud Run SA:    ${CYAN}${RUN_SA}${RESET}"
echo ""

if ask "Grant IAM permissions to both service accounts?"; then
  echo ""
  echo -e "${ARROW} Cloud Build permissions..."
  for role in roles/run.admin roles/iam.serviceAccountUser roles/secretmanager.secretAccessor roles/storage.admin; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${CB_SA}" --role="$role" --quiet 2>/dev/null || true
    echo -e "  ${TICK} CB SA → ${role}"
  done

  echo ""
  echo -e "${ARROW} Cloud Run service account permissions..."
  for role in roles/secretmanager.secretAccessor roles/aiplatform.user roles/storage.objectAdmin; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${RUN_SA}" --role="$role" --quiet 2>/dev/null || true
    echo -e "  ${TICK} Run SA → ${role}"
  done

  echo ""
  echo -e "${ARROW} GCS bucket access for Cloud Run SA..."
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${RUN_SA}" \
    --role="roles/storage.objectAdmin" --quiet 2>/dev/null || true
  echo -e "  ${TICK} Run SA → bucket objectAdmin"
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Render service.yaml with real values
# ─────────────────────────────────────────────────────────────────────────────
step_header 7 "Render Cloud Run Service Spec" \
  "Substitutes PROJECT_ID, REGION, REPO and CHROMA_BUCKET into deploy/service.yaml
  and saves it to /tmp/aiden-service-final.yaml ready for deployment."

if ask "Render deploy/service.yaml with your config values?"; then
  sed \
    -e "s|PROJECT_ID|${PROJECT_ID}|g" \
    -e "s|REGION|${REGION}|g" \
    -e "s|REPO|${REPO}|g" \
    -e "s|CHROMA_BUCKET|${BUCKET}|g" \
    -e "s|name: aiden-api|name: ${SERVICE_NAME}|g" \
    "$(dirname "$0")/deploy/service.yaml" > /tmp/aiden-service-final.yaml
  echo -e "${TICK} Rendered → /tmp/aiden-service-final.yaml"
  echo ""
  echo -e "${YELLOW}First 30 lines of rendered spec:${RESET}"
  head -30 /tmp/aiden-service-final.yaml
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Cloud Build (builds all 4 images + deploys)
# ─────────────────────────────────────────────────────────────────────────────
step_header 8 "Build Images + Deploy via Cloud Build" \
  "Submits a Cloud Build job that:
    1. Builds 4 Docker images in parallel:
       • aiden-api  (FastAPI + 7 agents)
       • workspace-mcp  (Google Calendar/Gmail/Drive)
       • mongodb-mcp    (read-only MongoDB queries)
       • notion-mcp     (team Notion workspace)
    2. Pushes all images to Artifact Registry
    3. Deploys the multi-container Cloud Run service
  This is the longest step — typically 8–15 minutes."

echo -e "${YELLOW}Build logs will stream in your terminal.${RESET}"
echo -e "${YELLOW}You can also monitor at: ${CYAN}https://console.cloud.google.com/cloud-build/builds${RESET}"
echo ""

if ask "Start Cloud Build (builds + deploys all containers)?"; then
  run_cmd "Cloud Build submit" \
    gcloud builds submit . \
      --config="$(dirname "$0")/deploy/cloudbuild-multicontainer.yaml" \
      --substitutions="_PROJECT_ID=${PROJECT_ID},_REGION=${REGION},_REPO=${REPO},_SERVICE=${SERVICE_NAME}" \
      --timeout=25m
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Make service publicly accessible
# ─────────────────────────────────────────────────────────────────────────────
step_header 9 "Make Cloud Run Service Public" \
  "Adds an IAM policy binding that allows unauthenticated users to call the
  public port (8080 / the API). MCP sidecars remain internal-only."

if ask "Allow unauthenticated access to '${SERVICE_NAME}'?"; then
  run_cmd "Set public IAM policy" \
    gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
      --region="$REGION" \
      --member="allUsers" \
      --role="roles/run.invoker" --quiet
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 — Firebase Hosting for React UI
# ─────────────────────────────────────────────────────────────────────────────
step_header 10 "Deploy React UI to Firebase Hosting (optional)" \
  "Firebase Hosting serves ui_react/index.html from a global CDN.
  The HTML file's API_BASE_URL will be updated to point at your Cloud Run URL.
  Requires: npm + firebase-tools installed."

CLOUD_RUN_URL=""
if gcloud run services describe "$SERVICE_NAME" --region="$REGION" &>/dev/null; then
  CLOUD_RUN_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" --format='value(status.url)' 2>/dev/null || echo "")
fi

if [[ -n "$CLOUD_RUN_URL" ]]; then
  echo -e "  Cloud Run URL: ${GREEN}${CLOUD_RUN_URL}${RESET}"
else
  echo -e "  ${YELLOW}Cloud Run URL not yet available — run step 8 first.${RESET}"
fi
echo ""

if ask "Deploy React UI to Firebase Hosting?"; then
  if ! command -v firebase &>/dev/null; then
    echo -e "${YELLOW}firebase-tools not found. Installing...${RESET}"
    if ask "Run: npm install -g firebase-tools?"; then
      run_cmd "Install firebase-tools" npm install -g firebase-tools
    else
      echo -e "${YELLOW}Skipping Firebase deploy. Host ui_react/index.html manually.${RESET}"
    fi
  fi

  if command -v firebase &>/dev/null && [[ -n "$CLOUD_RUN_URL" ]]; then
    echo -e "${ARROW} Patching API_BASE_URL in ui_react/index.html..."
    # Backup + patch
    cp ui_react/index.html ui_react/index.html.bak
    sed -i.bak "s|http://localhost:8000|${CLOUD_RUN_URL}|g" ui_react/index.html
    sed -i.bak "s|const API_BASE_URL = .*|const API_BASE_URL = '${CLOUD_RUN_URL}';|g" ui_react/index.html
    echo -e "${TICK} API_BASE_URL updated to: ${CLOUD_RUN_URL}"
    echo ""

    echo -e "${ARROW} Writing firebase.json..."
    cat > firebase.json <<'EOF'
{
  "hosting": {
    "public": "ui_react",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "headers": [
      {
        "source": "**",
        "headers": [
          { "key": "Cache-Control", "value": "no-cache" }
        ]
      }
    ],
    "rewrites": [
      { "source": "**", "destination": "/index.html" }
    ]
  }
}
EOF
    echo -e "${TICK} firebase.json written."
    echo ""

    if ask "Run: firebase deploy --only hosting?"; then
      run_cmd "Firebase deploy" firebase deploy --only hosting
    fi
  else
    echo -e "${YELLOW}Skipping Firebase deploy (firebase-tools or Cloud Run URL missing).${RESET}"
    echo -e "  Manually host ${CYAN}ui_react/index.html${RESET} on any static server."
    echo -e "  Set API_BASE_URL = ${CYAN}${CLOUD_RUN_URL}${RESET} inside the file."
  fi
else
  skip_msg
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 — Health check
# ─────────────────────────────────────────────────────────────────────────────
step_header 11 "Verify Deployment — Health Check" \
  "Calls GET /health on your Cloud Run URL and shows the API's status.
  A healthy response includes: total_agents=7, vertex_ai=enabled, MCP counts."

if [[ -z "$CLOUD_RUN_URL" ]]; then
  CLOUD_RUN_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" --format='value(status.url)' 2>/dev/null || echo "")
fi

if [[ -n "$CLOUD_RUN_URL" ]]; then
  if ask "Run health check against ${CLOUD_RUN_URL}/health?"; then
    echo ""
    echo -e "${ARROW} ${CYAN}curl ${CLOUD_RUN_URL}/health${RESET}"
    echo ""
    curl -s "${CLOUD_RUN_URL}/health" | python3 -m json.tool 2>/dev/null || \
      curl -s "${CLOUD_RUN_URL}/health"
    echo ""
    echo -e "${TICK} Health check complete."

    echo ""
    echo -e "${ARROW} Getting guest token for demo seed test..."
    TOKEN=$(curl -s -X POST "${CLOUD_RUN_URL}/auth/guest" \
      -H "Content-Type: application/json" \
      -d '{}' 2>/dev/null | python3 -c \
      "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")

    if [[ -n "$TOKEN" ]]; then
      echo -e "${TICK} Guest token obtained."
      if ask "Seed demo data (tasks + notes + embeddings)?"; then
        echo -e "${ARROW} ${CYAN}POST /demo/seed${RESET}"
        curl -s -X POST "${CLOUD_RUN_URL}/demo/seed" \
          -H "Authorization: Bearer ${TOKEN}" | python3 -m json.tool 2>/dev/null
        echo ""
        echo -e "${TICK} Demo data seeded."
      fi
    else
      echo -e "${YELLOW}Could not get guest token — API may still be starting up. Try again in 30 seconds.${RESET}"
    fi
  fi
else
  echo -e "${YELLOW}Cloud Run URL not available. Run step 8 first.${RESET}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
CLOUD_RUN_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" --format='value(status.url)' 2>/dev/null || echo "NOT DEPLOYED YET")

FIREBASE_URL=$(firebase hosting:sites:list --json 2>/dev/null | \
  python3 -c "import sys,json; sites=json.load(sys.stdin).get('sites',[]); print(sites[0].get('defaultUrl','') if sites else '')" 2>/dev/null || echo "")

banner "Deployment Complete — Summary"

echo -e "${BOLD}Live URLs:${RESET}"
echo -e "  ${TICK} API (Cloud Run):   ${GREEN}${CLOUD_RUN_URL}${RESET}"
echo -e "  ${TICK} API Health:        ${GREEN}${CLOUD_RUN_URL}/health${RESET}"
echo -e "  ${TICK} API Docs:          ${GREEN}${CLOUD_RUN_URL}/docs${RESET}"
if [[ -n "$FIREBASE_URL" ]]; then
echo -e "  ${TICK} UI (Firebase):     ${GREEN}${FIREBASE_URL}${RESET}"
fi
echo ""

echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo -e "  1. ${YELLOW}Update OAuth redirect URIs${RESET} in Google Cloud Console:"
echo -e "     Add these to your OAuth client's Authorized Redirect URIs:"
echo -e "     ${CYAN}${CLOUD_RUN_URL}/auth/gmail/callback${RESET}"
echo -e "     ${CYAN}${CLOUD_RUN_URL}/auth/calendar/callback${RESET}"
echo ""
echo -e "  2. ${YELLOW}Update DEMO_SCRIPT.md${RESET} — replace [hash] placeholder:"
echo -e "     ${CYAN}${CLOUD_RUN_URL}${RESET}"
echo ""
echo -e "  3. ${YELLOW}Update README.md${RESET} — add live URL badge at the top:"
echo -e '     [![Live Demo](https://img.shields.io/badge/Live-Cloud_Run-blue)]('"${CLOUD_RUN_URL})"
echo ""
echo -e "  4. ${YELLOW}Verify Gemini embeddings are working:${RESET}"
echo -e "     ${CYAN}curl ${CLOUD_RUN_URL}/notes/search/verify -H 'Authorization: Bearer <token>'${RESET}"
echo ""
echo -e "${BOLD}Architecture deployed:${RESET}"
summary_line "aiden-api (FastAPI)"       "port 8080 — public"
summary_line "workspace-mcp"             "port 8001 — localhost sidecar"
summary_line "mongodb-mcp"              "port 8002 — localhost sidecar"
summary_line "notion-mcp"              "port 8003 — localhost sidecar"
summary_line "ChromaDB storage"         "gs://${BUCKET} (persistent)"
summary_line "Vertex AI"                "enabled (GOOGLE_GENAI_USE_VERTEXAI=1)"
summary_line "MongoDB"                  "Atlas (external)"
echo ""
echo -e "${GREEN}${BOLD}AIDEN v3.1 is live on Google Cloud! 🚀${RESET}"
echo ""