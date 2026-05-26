#!/bin/bash
# SahAIyak — Complete GCP Deployment Script
# Run from project root: bash scripts/gcp_deploy.sh
# Prerequisites: gcloud CLI installed and authenticated as avinashgehi3@gmail.com

set -e

PROJECT_ID="sahaiyak"
REGION="asia-south1"
SERVICE_NAME="sahayak-api"
DB_INSTANCE="sahayak-db"
REDIS_INSTANCE="sahayak-redis"
VPC_CONNECTOR="sahayak-vpc"
DB_PASSWORD="SahAIyak@2026!Secure"

echo "=== SahAIyak GCP Deployment ==="
echo "Project: ${PROJECT_ID} | Region: ${REGION}"

# 1. Set project
gcloud config set project ${PROJECT_ID}

# 2. Enable all required APIs
echo "[1/9] Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  vpcaccess.googleapis.com \
  storage.googleapis.com \
  firebase.googleapis.com 2>/dev/null || true

# 3. Create Artifact Registry repo
echo "[2/9] Creating Artifact Registry..."
gcloud artifacts repositories create sahayak-repo \
  --repository-format=docker \
  --location=${REGION} \
  --description="SahAIyak container images" 2>/dev/null || echo "  (already exists)"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/sahayak-repo/${SERVICE_NAME}"

# 4. Create Cloud SQL instance
echo "[3/9] Creating Cloud SQL PostgreSQL instance..."
gcloud sql instances create ${DB_INSTANCE} \
  --database-version=POSTGRES_15 \
  --region=${REGION} \
  --tier=db-f1-micro \
  --storage-size=10GB \
  --storage-type=SSD \
  --no-backup \
  --authorized-networks=0.0.0.0/0 2>/dev/null || echo "  (already exists)"

# Set postgres user password
gcloud sql users set-password postgres \
  --instance=${DB_INSTANCE} \
  --password="${DB_PASSWORD}" 2>/dev/null || true

# Create database
gcloud sql databases create sahayak --instance=${DB_INSTANCE} 2>/dev/null || true

DB_IP=$(gcloud sql instances describe ${DB_INSTANCE} --format='value(ipAddresses[0].ipAddress)')
echo "  Cloud SQL IP: ${DB_IP}"
DATABASE_URL="postgresql://postgres:${DB_PASSWORD}@${DB_IP}/sahayak"

# 5. Create VPC connector for Memorystore Redis access
echo "[4/9] Creating VPC connector..."
gcloud compute networks vpc-access connectors create ${VPC_CONNECTOR} \
  --network=default \
  --region=${REGION} \
  --range=10.8.0.0/28 2>/dev/null || echo "  (already exists)"

# 6. Create Memorystore Redis
echo "[5/9] Creating Memorystore Redis..."
gcloud redis instances create ${REDIS_INSTANCE} \
  --size=1 \
  --region=${REGION} \
  --redis-version=redis_7_0 \
  --tier=basic \
  --network=default 2>/dev/null || echo "  (already exists)"

REDIS_IP=$(gcloud redis instances describe ${REDIS_INSTANCE} --region=${REGION} --format='value(host)')
echo "  Redis IP: ${REDIS_IP}"
REDIS_URL="redis://${REDIS_IP}:6379"

# 7. Store secrets in Secret Manager
echo "[6/9] Storing secrets..."
_secret() {
  local name=$1; local val=$2
  echo -n "$val" | gcloud secrets create "$name" --data-file=- 2>/dev/null || \
  echo -n "$val" | gcloud secrets versions add "$name" --data-file=-
}

# Load .env for API keys
set -a; source .env; set +a

_secret GEMINI_API_KEY "${GEMINI_API_KEY}"
_secret GROQ_API_KEY "${GROQ_API_KEY}"
_secret ELEVENLABS_API_KEY "${ELEVENLABS_API_KEY}"
_secret PINECONE_API_KEY "${PINECONE_API_KEY}"
_secret PINECONE_HOST "${PINECONE_HOST}"
_secret DATABASE_URL "${DATABASE_URL}"
_secret REDIS_URL "${REDIS_URL}"

# Grant Cloud Run SA access to secrets
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for secret in GEMINI_API_KEY GROQ_API_KEY ELEVENLABS_API_KEY PINECONE_API_KEY PINECONE_HOST DATABASE_URL REDIS_URL; do
  gcloud secrets add-iam-policy-binding "$secret" \
    --member="$SA" \
    --role="roles/secretmanager.secretAccessor" 2>/dev/null || true
done

# 8. Build and push Docker image via Cloud Build
echo "[7/9] Building Docker image..."
gcloud builds submit \
  --tag "${IMAGE}:latest" \
  --timeout=600s

# 9. Deploy to Cloud Run with VPC connector for Redis
echo "[8/9] Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image="${IMAGE}:latest" \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --timeout=300 \
  --vpc-connector=${VPC_CONNECTOR} \
  --vpc-egress=private-ranges-only \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,GROQ_API_KEY=GROQ_API_KEY:latest,ELEVENLABS_API_KEY=ELEVENLABS_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest,PINECONE_HOST=PINECONE_HOST:latest,DATABASE_URL=DATABASE_URL:latest,REDIS_URL=REDIS_URL:latest" \
  --set-env-vars="ENVIRONMENT=production,PINECONE_INDEX=sahayak-judgments,DATA_RETENTION_DAYS=30"

CLOUD_RUN_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(status.url)')
echo "  Cloud Run URL: ${CLOUD_RUN_URL}"

# 9. Everything runs on Cloud Run — frontend served by FastAPI
echo "[9/9] Verifying deployment..."
echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo "App (frontend + API) : ${CLOUD_RUN_URL}"
echo "Health check         : curl ${CLOUD_RUN_URL}/health"
echo "Frontend             : ${CLOUD_RUN_URL}/"
echo "Dashboard            : ${CLOUD_RUN_URL}/dashboard"
echo ""
echo "Next steps:"
echo "  1. Run judgment ingestion:"
echo "     python scripts/ingest_judgments.py --gcs gs://sahaiyak/archive/"
echo "  2. Test API: curl ${CLOUD_RUN_URL}/health"
echo "  3. Open browser: ${CLOUD_RUN_URL}/"
