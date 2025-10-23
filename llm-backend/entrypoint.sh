#!/bin/bash
set -e

echo "========================================="
echo "Starting Learn Like Magic Backend"
echo "========================================="
echo "Environment: ${ENVIRONMENT:-development}"
echo "API Host: ${API_HOST:-0.0.0.0}"
echo "API Port: ${API_PORT:-8000}"
echo "LLM Model: ${LLM_MODEL:-gpt-4o-mini}"
echo ""

# Check critical environment variables
echo "Checking environment variables..."
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL is not set"
    exit 1
fi
echo "✓ DATABASE_URL is set"

if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY is not set"
    echo "Please ensure the secret is properly configured in App Runner"
    exit 1
fi
echo "✓ OPENAI_API_KEY is set"

echo ""
echo "Note: Database migrations should be run manually before first deployment"
echo "Run: python db.py --migrate && python db.py --seed-guidelines data/seed_guidelines.json"
echo ""
echo "Starting Uvicorn server..."
echo "========================================="

exec uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info
