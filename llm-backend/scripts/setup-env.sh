#!/bin/bash
# Setup .env file from terraform.tfvars for local development

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
TFVARS_FILE="$BACKEND_DIR/../infra/terraform/terraform.tfvars"

echo "🔧 Setting up .env file for local development..."

# Check if terraform.tfvars exists
if [ ! -f "$TFVARS_FILE" ]; then
    echo "❌ Error: terraform.tfvars not found at $TFVARS_FILE"
    echo "Please create it or copy .env.example manually"
    exit 1
fi

# Extract values from terraform.tfvars
DB_USER=$(grep '^db_user' "$TFVARS_FILE" | cut -d'=' -f2 | tr -d ' "')
DB_PASSWORD=$(grep '^db_password' "$TFVARS_FILE" | cut -d'=' -f2 | tr -d ' "')
DB_NAME=$(grep '^db_name' "$TFVARS_FILE" | cut -d'=' -f2 | tr -d ' "')
OPENAI_API_KEY=$(grep '^openai_api_key' "$TFVARS_FILE" | cut -d'=' -f2 | tr -d ' "')

# Database endpoint (from production)
DB_ENDPOINT="learnlikemagic-production.cluster-cgp4ua06a7ei.us-east-1.rds.amazonaws.com"

# Create .env file
cat > "$BACKEND_DIR/.env" << EOF
# LLM API Keys (provider/model selection is in DB llm_config table)
OPENAI_API_KEY=$OPENAI_API_KEY

# Database (Production PostgreSQL)
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@$DB_ENDPOINT:5432/$DB_NAME

# Database Connection Pool Settings
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Application Settings
LOG_LEVEL=INFO
ENVIRONMENT=development
EOF

echo "✅ .env file created successfully at $BACKEND_DIR/.env"
echo ""
echo "⚠️  Note: This .env uses PRODUCTION database credentials."
echo "   Be careful with write operations!"
echo ""
echo "📝 To use a local database instead, edit .env and change DATABASE_URL"
