.PHONY: help init plan apply destroy outputs gh-secrets tf-fmt tf-validate clean

# Default target
help:
	@echo "Learn Like Magic - Terraform Automation"
	@echo ""
	@echo "Available targets:"
	@echo "  init          - Initialize Terraform"
	@echo "  plan          - Show Terraform execution plan"
	@echo "  apply         - Apply Terraform configuration"
	@echo "  destroy       - Destroy all infrastructure"
	@echo "  outputs       - Show Terraform outputs"
	@echo "  gh-secrets    - Export outputs to GitHub secrets (requires gh CLI)"
	@echo "  tf-fmt        - Format Terraform files"
	@echo "  tf-validate   - Validate Terraform configuration"
	@echo "  clean         - Clean Terraform files"
	@echo ""
	@echo "Prerequisites:"
	@echo "  - terraform (brew install terraform)"
	@echo "  - aws CLI configured (aws configure)"
	@echo "  - gh CLI for gh-secrets (brew install gh)"
	@echo "  - terraform.tfvars file (cp terraform.tfvars.example terraform.tfvars)"

# Initialize Terraform
init:
	@echo "Initializing Terraform..."
	terraform init

# Show execution plan
plan:
	@echo "Generating Terraform plan..."
	terraform plan

# Apply configuration
apply:
	@echo "Applying Terraform configuration..."
	@echo "⚠️  This will create AWS resources and incur costs!"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		terraform apply; \
	else \
		echo "Cancelled."; \
	fi

# Destroy all resources
destroy:
	@echo "⚠️  WARNING: This will destroy ALL infrastructure!"
	@echo "⚠️  Database data will be LOST!"
	@read -p "Are you SURE? Type 'destroy' to confirm: " confirm; \
	if [ "$$confirm" = "destroy" ]; then \
		terraform destroy; \
	else \
		echo "Cancelled."; \
	fi

# Show outputs
outputs:
	@echo "Terraform Outputs:"
	@echo ""
	@terraform output

# Export outputs to GitHub secrets
gh-secrets:
	@echo "Exporting Terraform outputs to GitHub secrets..."
	@command -v gh >/dev/null 2>&1 || { echo "Error: gh CLI not installed. Run: brew install gh"; exit 1; }
	@command -v jq >/dev/null 2>&1 || { echo "Error: jq not installed. Run: brew install jq"; exit 1; }
	@echo "Authenticating with GitHub..."
	@gh auth status || gh auth login
	@echo "Setting secrets..."
	@for key in $$(terraform output -json github_secrets | jq -r 'keys[]'); do \
		value=$$(terraform output -json github_secrets | jq -r ".[\"$$key\"]"); \
		echo "Setting $$key..."; \
		gh secret set "$$key" --body "$$value" || echo "Failed to set $$key"; \
	done
	@echo ""
	@echo "✅ GitHub secrets set successfully!"
	@echo "View at: https://github.com/$$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/')/settings/secrets/actions"

# Format Terraform files
tf-fmt:
	@echo "Formatting Terraform files..."
	terraform fmt -recursive

# Validate configuration
tf-validate:
	@echo "Validating Terraform configuration..."
	terraform validate

# Clean Terraform files
clean:
	@echo "Cleaning Terraform files..."
	rm -rf .terraform
	rm -f .terraform.lock.hcl
	rm -f terraform.tfstate.backup
	@echo "✅ Cleaned (kept terraform.tfstate)"

# Quick deployment summary
summary:
	@echo "==================================="
	@echo "Deployment Summary"
	@echo "==================================="
	@terraform output deployment_summary

# Database connection string
db-url:
	@echo "Database URL (copy to .env):"
	@terraform output -raw database_url

# Frontend URL
fe-url:
	@echo "Frontend URL:"
	@terraform output -raw frontend_url

# Backend URL
be-url:
	@echo "Backend API URL:"
	@terraform output -raw app_runner_service_url

# All URLs
urls: fe-url be-url

# Initial setup guide
setup:
	@echo "Initial Setup Guide"
	@echo "==================="
	@echo ""
	@echo "1. Configure terraform.tfvars:"
	@echo "   cp terraform.tfvars.example terraform.tfvars"
	@echo "   nano terraform.tfvars  # Add your values"
	@echo ""
	@echo "2. Initialize Terraform:"
	@echo "   make init"
	@echo ""
	@echo "3. Review plan:"
	@echo "   make plan"
	@echo ""
	@echo "4. Apply infrastructure:"
	@echo "   make apply"
	@echo ""
	@echo "5. Export GitHub secrets:"
	@echo "   make gh-secrets"
	@echo ""
	@echo "6. View deployment summary:"
	@echo "   make summary"
