variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "learnlikemagic"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "production"
}

variable "github_org" {
  description = "GitHub organization or username"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "learnlikemagic"
}

#############################################################################
# Database Variables
#############################################################################

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "tutor"
}

variable "db_user" {
  description = "Database master username"
  type        = string
  default     = "llmuser"
}

variable "db_password" {
  description = "Database master password (sensitive)"
  type        = string
  sensitive   = true
}

#############################################################################
# Application Variables
#############################################################################

variable "openai_api_key" {
  description = "OpenAI API key (sensitive)"
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  description = "Google Gemini API key (sensitive)"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude models (sensitive)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tutor_llm_provider" {
  description = "LLM provider for tutor workflow: openai, anthropic, or anthropic-haiku"
  type        = string
  default     = "openai"
}

variable "llm_model" {
  description = "OpenAI model to use"
  type        = string
  default     = "gpt-4o-mini"
}

#############################################################################
# Frontend Variables
#############################################################################

variable "domain_names" {
  description = "Custom domain names for CloudFront (optional)"
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for custom domain (optional, must be in us-east-1)"
  type        = string
  default     = ""
}
