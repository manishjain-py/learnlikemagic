variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "github_org" {
  description = "GitHub organization or username"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
}

variable "ecr_repository_arn" {
  description = "ECR repository ARN for policy attachment"
  type        = string
}

variable "s3_bucket_arn" {
  description = "S3 bucket ARN for policy attachment"
  type        = string
}

variable "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for policy attachment"
  type        = string
}

variable "app_runner_service_arn" {
  description = "App Runner service ARN for policy attachment"
  type        = string
}
