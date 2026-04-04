set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID env var first}"
REGION="${REGION:-us-central1}"
REPO="aiden"
SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"

echo "🔧 Configuring GCP project: $PROJECT_ID (region: $REGION)"
gcloud config set project "$PROJECT_ID"

echo "📡 Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  cloudresourcemanager.googleapis.com

echo "📦 Creating Artifact Registry repository..."
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="AIDEN container images" \
  2>/dev/null || echo "  (repository already exists)"

echo "🔐 Creating secrets in Secret Manager..."
echo "  Enter values when prompted. Press Ctrl+C to skip any."

create_secret() {
  local name="$1"
  local prompt="$2"
  if gcloud secrets describe "$name" &>/dev/null; then
    echo "  Secret $name already exists — skipping"
    return
  fi
  echo -n "  $prompt: "
  read -rs value
  echo
  printf '%s' "$value" | gcloud secrets create "$name" --data-file=-
  echo "  ✓ Created secret: $name"
}

create_secret "AIDEN_MONGO_URI"          "MongoDB URI (e.g. mongodb+srv://...)"
create_secret "AIDEN_GEMINI_API_KEY"     "Gemini API Key"
create_secret "AIDEN_JWT_SECRET"         "JWT Secret (min 32 chars)"
create_secret "AIDEN_GOOGLE_CLIENT_ID"   "Google OAuth Client ID"
create_secret "AIDEN_GOOGLE_CLIENT_SECRET" "Google OAuth Client Secret"

echo "🔑 Granting Secret Manager access to service account..."
for secret in AIDEN_MONGO_URI AIDEN_GEMINI_API_KEY AIDEN_JWT_SECRET \
              AIDEN_GOOGLE_CLIENT_ID AIDEN_GOOGLE_CLIENT_SECRET; do
  gcloud secrets add-iam-policy-binding "$secret" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet 2>/dev/null || true
done

echo "🏗  Granting Cloud Build permissions..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

for role in roles/run.admin roles/iam.serviceAccountUser roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$CB_SA" \
    --role="$role" --quiet
done

echo "🐳 Configuring Docker auth..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo ""
echo "✅ GCP setup complete!"
echo ""
echo "Next: deploy with:"
echo "  gcloud builds submit --config=cloudbuild.yaml \\"
echo "    --substitutions=_PROJECT_ID=$PROJECT_ID"
echo ""
echo "Or locally:"
echo "  export GOOGLE_CLOUD_PROJECT=$PROJECT_ID"
echo "  gcloud auth application-default login"
echo "  uvicorn src.api.main:app --reload"
