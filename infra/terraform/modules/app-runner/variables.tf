variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "ecr_repository_url" {
  description = "ECR repository URL for backend image"
  type        = string
}

variable "database_url" {
  description = "PostgreSQL connection string"
  type        = string
  sensitive   = true
}

variable "openai_secret_arn" {
  description = "ARN of OpenAI API key secret in Secrets Manager"
  type        = string
}

variable "gemini_secret_arn" {
  description = "ARN of Gemini API key secret in Secrets Manager"
  type        = string
}

variable "llm_model" {
  description = "OpenAI model to use"
  type        = string
  default     = "gpt-4o-mini"
}

variable "s3_books_bucket" {
  description = "S3 bucket name for book ingestion storage"
  type        = string
  default     = "learnlikemagic-books"
}
