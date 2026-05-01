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

variable "anthropic_secret_arn" {
  description = "ARN of Anthropic API key secret in Secrets Manager"
  type        = string
  default     = ""
}

variable "elevenlabs_secret_arn" {
  description = "ARN of ElevenLabs API key secret in Secrets Manager. Empty string when EL is not provisioned."
  type        = string
  default     = ""
}

variable "tts_provider" {
  description = "TTS provider env value: 'elevenlabs' or 'google_tts'. Admin DB row overrides at runtime."
  type        = string
  default     = "elevenlabs"
}

variable "tutor_llm_provider" {
  description = "LLM provider for tutor workflow"
  type        = string
  default     = "openai"
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

variable "cognito_app_client_id" {
  description = "Cognito User Pool app client ID"
  type        = string
}

variable "cognito_region" {
  description = "AWS region for Cognito User Pool"
  type        = string
  default     = "us-east-1"
}

variable "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  type        = string
}

variable "google_cloud_tts_api_key" {
  description = "Google Cloud TTS API key (plain-text env var; matches manual prod state)"
  type        = string
  sensitive   = true
}
