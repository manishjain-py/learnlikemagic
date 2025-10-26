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
