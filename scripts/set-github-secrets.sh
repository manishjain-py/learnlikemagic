#!/bin/bash
# Script to set GitHub secrets from Terraform outputs
# Usage: ./scripts/set-github-secrets.sh

set -e

echo "========================================="
echo "Setting GitHub Secrets"
echo "========================================="
echo ""

# Check if gh CLI is authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated with GitHub CLI"
    echo ""
    echo "Please run: gh auth login"
    echo "Then run this script again."
    exit 1
fi

echo "✓ GitHub CLI authenticated"
echo ""

# Navigate to terraform directory
cd "$(dirname "$0")/../infra/terraform"

echo "Fetching secrets from Terraform outputs..."
echo ""

# Set each secret
echo "Setting AWS_REGION..."
gh secret set AWS_REGION --body "us-east-1"

echo "Setting AWS_ROLE_ARN..."
gh secret set AWS_ROLE_ARN --body "arn:aws:iam::926211191776:role/learnlikemagic-github-actions-production"

echo "Setting ECR_REGISTRY..."
gh secret set ECR_REGISTRY --body "926211191776.dkr.ecr.us-east-1.amazonaws.com"

echo "Setting ECR_REPOSITORY..."
gh secret set ECR_REPOSITORY --body "learnlikemagic-backend-production"

echo "Setting APP_RUNNER_SERVICE_ARN..."
gh secret set APP_RUNNER_SERVICE_ARN --body "arn:aws:apprunner:us-east-1:926211191776:service/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd"

echo "Setting FRONTEND_BUCKET..."
gh secret set FRONTEND_BUCKET --body "learnlikemagic-frontend-production"

echo "Setting CLOUDFRONT_DISTRIBUTION_ID..."
gh secret set CLOUDFRONT_DISTRIBUTION_ID --body "E19EYV4ZGTL1L9"

echo "Setting VITE_API_URL..."
gh secret set VITE_API_URL --body "https://ypwbjbcmbd.us-east-1.awsapprunner.com"

echo ""
echo "========================================="
echo "✅ All GitHub secrets set successfully!"
echo "========================================="
echo ""
echo "You can verify at:"
echo "https://github.com/manishjain-py/learnlikemagic/settings/secrets/actions"
echo ""
echo "Next steps:"
echo "  1. Go to https://github.com/manishjain-py/learnlikemagic/actions"
echo "  2. Re-run the failed workflow"
echo "  3. Or push a new commit to trigger deployment"
