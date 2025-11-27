output "openai_api_key_secret_arn" {
  description = "ARN of OpenAI API key secret"
  value       = aws_secretsmanager_secret.openai_api_key.arn
}

output "db_password_secret_arn" {
  description = "ARN of database password secret"
  value       = aws_secretsmanager_secret.db_password.arn
}

output "gemini_api_key_secret_arn" {
  description = "ARN of Gemini API key secret"
  value       = aws_secretsmanager_secret.gemini_api_key.arn
}
