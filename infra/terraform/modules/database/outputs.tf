output "instance_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.database.address
}

output "instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.database.identifier
}

output "instance_arn" {
  description = "RDS instance ARN"
  value       = aws_db_instance.database.arn
}

output "database_name" {
  description = "Database name"
  value       = aws_db_instance.database.db_name
}

output "database_url" {
  description = "Full PostgreSQL connection string"
  value       = "postgresql://${var.db_user}:${var.db_password}@${aws_db_instance.database.address}:5432/${var.db_name}"
  sensitive   = true
}

output "security_group_id" {
  description = "Security group ID for database"
  value       = aws_security_group.database.id
}
