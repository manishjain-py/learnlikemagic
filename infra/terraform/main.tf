terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "LearnLikeMagic"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Data sources for current AWS account and region
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# VPC and Networking (using default VPC for simplicity)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

#############################################################################
# Secrets Management
#############################################################################

module "secrets" {
  source = "./modules/secrets"

  project_name   = var.project_name
  environment    = var.environment
  openai_api_key = var.openai_api_key
  db_password    = var.db_password
}

#############################################################################
# Database (Aurora Serverless v2 PostgreSQL)
#############################################################################

module "database" {
  source = "./modules/database"

  project_name = var.project_name
  environment  = var.environment
  db_name      = var.db_name
  db_user      = var.db_user
  db_password  = var.db_password
  vpc_id       = data.aws_vpc.default.id
  subnet_ids   = data.aws_subnets.default.ids
}

#############################################################################
# ECR (Container Registry)
#############################################################################

module "ecr" {
  source = "./modules/ecr"

  project_name = var.project_name
  environment  = var.environment
}

#############################################################################
# App Runner (Backend Service)
#############################################################################

module "app_runner" {
  source = "./modules/app-runner"

  project_name       = var.project_name
  environment        = var.environment
  ecr_repository_url = module.ecr.repository_url
  database_url       = module.database.database_url
  openai_secret_arn  = module.secrets.openai_api_key_secret_arn
  llm_model          = var.llm_model
  s3_books_bucket    = "learnlikemagic-books"

  depends_on = [
    module.database,
    module.secrets,
    module.ecr
  ]
}

#############################################################################
# Frontend (S3 + CloudFront)
#############################################################################

module "frontend" {
  source = "./modules/frontend"

  project_name        = var.project_name
  environment         = var.environment
  api_endpoint_url    = module.app_runner.service_url
  domain_names        = var.domain_names
  acm_certificate_arn = var.acm_certificate_arn

  depends_on = [module.app_runner]
}

#############################################################################
# GitHub OIDC (CI/CD Integration)
#############################################################################

module "github_oidc" {
  source = "./modules/github-oidc"

  project_name               = var.project_name
  environment                = var.environment
  github_org                 = var.github_org
  github_repo                = var.github_repo
  ecr_repository_arn         = module.ecr.repository_arn
  s3_bucket_arn              = module.frontend.s3_bucket_arn
  cloudfront_distribution_id = module.frontend.cloudfront_distribution_id
  app_runner_service_arn     = module.app_runner.service_arn
}
