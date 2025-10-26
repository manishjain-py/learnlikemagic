output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

output "aws_account_id" {
  description = "AWS account ID"
  value       = data.aws_caller_identity.current.account_id
}

#############################################################################
# Database Outputs
#############################################################################

output "database_endpoint" {
  description = "Aurora cluster endpoint"
  value       = module.database.cluster_endpoint
}

output "database_url" {
  description = "Full PostgreSQL connection string"
  value       = module.database.database_url
  sensitive   = true
}

#############################################################################
# ECR Outputs
#############################################################################

output "ecr_repository_url" {
  description = "ECR repository URL for backend Docker images"
  value       = module.ecr.repository_url
}

output "ecr_repository_name" {
  description = "ECR repository name"
  value       = module.ecr.repository_name
}

#############################################################################
# App Runner Outputs
#############################################################################

output "app_runner_service_url" {
  description = "App Runner service URL (backend API)"
  value       = module.app_runner.service_url
}

output "app_runner_service_arn" {
  description = "App Runner service ARN"
  value       = module.app_runner.service_arn
}

#############################################################################
# Frontend Outputs
#############################################################################

output "frontend_bucket_name" {
  description = "S3 bucket name for frontend"
  value       = module.frontend.s3_bucket_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = module.frontend.cloudfront_distribution_id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain name (frontend URL)"
  value       = module.frontend.cloudfront_domain_name
}

output "frontend_url" {
  description = "Frontend URL (HTTPS)"
  value       = "https://${module.frontend.cloudfront_domain_name}"
}

#############################################################################
# GitHub OIDC Outputs
#############################################################################

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions"
  value       = module.github_oidc.role_arn
}

#############################################################################
# Environment Variables for GitHub Secrets
#############################################################################

output "github_secrets" {
  description = "Environment variables to set as GitHub secrets"
  value = {
    AWS_REGION                 = var.aws_region
    AWS_ROLE_ARN               = module.github_oidc.role_arn
    ECR_REPOSITORY             = module.ecr.repository_name
    ECR_REGISTRY               = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    APP_RUNNER_SERVICE_ARN     = module.app_runner.service_arn
    FRONTEND_BUCKET            = module.frontend.s3_bucket_name
    CLOUDFRONT_DISTRIBUTION_ID = module.frontend.cloudfront_distribution_id
    VITE_API_URL               = module.app_runner.service_url
  }
}

#############################################################################
# Summary Output
#############################################################################

output "deployment_summary" {
  description = "Deployment summary"
  value       = <<-EOT

    ========================================
    Learn Like Magic - Deployment Summary
    ========================================

    Frontend URL:    https://${module.frontend.cloudfront_domain_name}
    Backend API:     ${module.app_runner.service_url}
    Database:        ${module.database.cluster_endpoint}

    ECR Repository:  ${module.ecr.repository_url}
    S3 Bucket:       ${module.frontend.s3_bucket_name}
    CloudFront ID:   ${module.frontend.cloudfront_distribution_id}

    GitHub Actions:
    - Role ARN:      ${module.github_oidc.role_arn}

    Next Steps:
    1. Export secrets to GitHub: make gh-secrets
    2. Push code to trigger deployment
    3. Visit your frontend URL

    ========================================
  EOT
}
