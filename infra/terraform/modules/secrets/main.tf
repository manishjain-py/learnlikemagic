# AWS Secrets Manager for Sensitive Configuration

resource "aws_secretsmanager_secret" "openai_api_key" {
  name        = "${var.project_name}-${var.environment}-openai-api-key"
  description = "OpenAI API key for LLM integration"

  recovery_window_in_days = 7 # Allow recovery within 7 days if deleted

  tags = {
    Name        = "${var.project_name}-openai-api-key"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  secret_id     = aws_secretsmanager_secret.openai_api_key.id
  secret_string = var.openai_api_key
}

resource "aws_secretsmanager_secret" "db_password" {
  name        = "${var.project_name}-${var.environment}-db-password"
  description = "Database master password"

  recovery_window_in_days = 7

  tags = {
    Name        = "${var.project_name}-db-password"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.db_password
}

resource "aws_secretsmanager_secret" "gemini_api_key" {
  name        = "${var.project_name}-${var.environment}-gemini-api-key"
  description = "Google Gemini API key for LLM integration"

  recovery_window_in_days = 7 # Allow recovery within 7 days if deleted

  tags = {
    Name        = "${var.project_name}-gemini-api-key"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "gemini_api_key" {
  secret_id     = aws_secretsmanager_secret.gemini_api_key.id
  secret_string = var.gemini_api_key
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  count       = var.anthropic_api_key != "" ? 1 : 0
  name        = "${var.project_name}-${var.environment}-anthropic-api-key"
  description = "Anthropic API key for Claude models"

  recovery_window_in_days = 7

  tags = {
    Name        = "${var.project_name}-anthropic-api-key"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  count         = var.anthropic_api_key != "" ? 1 : 0
  secret_id     = aws_secretsmanager_secret.anthropic_api_key[0].id
  secret_string = var.anthropic_api_key
}
