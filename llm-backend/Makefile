.PHONY: help build build-local build-prod push test run clean db-migrate db-seed

# Learn Like Magic Backend - Build & Deployment Automation
# See docs/dev-workflow.md for complete development guide

# Default target
help:
	@echo "Learn Like Magic Backend - Makefile Commands"
	@echo ""
	@echo "Development:"
	@echo "  run           - Run the application locally"
	@echo "  test          - Run tests"
	@echo "  clean         - Clean up build artifacts"
	@echo ""
	@echo "Database:"
	@echo "  db-migrate    - Run database migrations"
	@echo "  db-seed       - Seed database with teaching guidelines"
	@echo ""
	@echo "Docker (Local Development):"
	@echo "  build-local   - Build Docker image for local development (ARM64 on Mac)"
	@echo "  run-docker    - Run Docker container locally"
	@echo ""
	@echo "Docker (Production - AWS App Runner):"
	@echo "  build-prod    - Build Docker image for AWS App Runner (AMD64)"
	@echo "  push          - Push image to ECR (requires AWS credentials)"
	@echo "  deploy        - Build, push, and trigger App Runner deployment"
	@echo ""
	@echo "⚠️  IMPORTANT: AWS App Runner requires AMD64 architecture!"
	@echo "   Always use 'make build-prod' before pushing to ECR"

# Local development
run:
	@echo "Starting application locally..."
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

test:
	@echo "Running tests..."
	pytest

# Database operations
db-migrate:
	@echo "Running database migrations..."
	python db.py --migrate

db-seed:
	@echo "Seeding database with teaching guidelines..."
	python db.py --seed-guidelines data/seed_guidelines.json

# Docker builds
build-local:
	@echo "Building Docker image for local development..."
	@echo "Platform: $(shell uname -m)"
	docker build -t learnlikemagic-backend:local .
	@echo "✓ Local image built successfully"

build-prod:
	@echo "========================================="
	@echo "Building Docker image for AWS App Runner"
	@echo "========================================="
	@echo "Target platform: linux/amd64"
	@echo ""
	docker buildx build --platform linux/amd64 \
		-t learnlikemagic-backend:amd64 \
		-t learnlikemagic-backend:latest \
		--load .
	@echo ""
	@echo "✓ Production image built successfully for AMD64"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Tag for ECR:  make tag-ecr"
	@echo "  2. Push to ECR:  make push"
	@echo "  3. Or run:       make deploy"

run-docker:
	@echo "Running Docker container locally..."
	docker run --rm -p 8000:8000 \
		--env-file .env \
		learnlikemagic-backend:local

# ECR operations (requires environment variables)
ECR_REGISTRY ?= 926211191776.dkr.ecr.us-east-1.amazonaws.com
ECR_REPOSITORY ?= learnlikemagic-backend-production
AWS_REGION ?= us-east-1

ecr-login:
	@echo "Logging into Amazon ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | \
		docker login --username AWS --password-stdin $(ECR_REGISTRY)

tag-ecr:
	@echo "Tagging image for ECR..."
	docker tag learnlikemagic-backend:amd64 $(ECR_REGISTRY)/$(ECR_REPOSITORY):latest
	docker tag learnlikemagic-backend:amd64 $(ECR_REGISTRY)/$(ECR_REPOSITORY):$(shell git rev-parse --short HEAD)
	@echo "✓ Tagged for ECR"

push: ecr-login tag-ecr
	@echo "Pushing image to ECR..."
	docker push $(ECR_REGISTRY)/$(ECR_REPOSITORY):latest
	docker push $(ECR_REGISTRY)/$(ECR_REPOSITORY):$(shell git rev-parse --short HEAD)
	@echo "✓ Image pushed to ECR"

deploy: build-prod push
	@echo "Triggering App Runner deployment..."
	@if [ -z "$$APP_RUNNER_SERVICE_ARN" ]; then \
		echo "ERROR: APP_RUNNER_SERVICE_ARN environment variable not set"; \
		echo "Run: export APP_RUNNER_SERVICE_ARN=<your-service-arn>"; \
		exit 1; \
	fi
	aws apprunner start-deployment --service-arn $$APP_RUNNER_SERVICE_ARN --region $(AWS_REGION)
	@echo "✓ Deployment triggered"
	@echo ""
	@echo "Monitor deployment:"
	@echo "  aws apprunner describe-service --service-arn $$APP_RUNNER_SERVICE_ARN --region $(AWS_REGION)"

# Cleanup
clean:
	@echo "Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "✓ Cleaned up"

# Architecture check
check-arch:
	@echo "System Architecture: $(shell uname -m)"
	@echo ""
	@echo "Docker Images:"
	@docker images learnlikemagic-backend --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}"
	@echo ""
	@echo "Note: AWS App Runner requires AMD64 architecture"
	@echo "      Mac M-series is ARM64 - always use 'make build-prod'"
