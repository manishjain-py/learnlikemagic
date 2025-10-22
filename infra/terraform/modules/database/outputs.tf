output "cluster_endpoint" {
  description = "Aurora cluster writer endpoint"
  value       = aws_rds_cluster.database.endpoint
}

output "cluster_reader_endpoint" {
  description = "Aurora cluster reader endpoint"
  value       = aws_rds_cluster.database.reader_endpoint
}

output "cluster_id" {
  description = "Aurora cluster ID"
  value       = aws_rds_cluster.database.cluster_identifier
}

output "cluster_arn" {
  description = "Aurora cluster ARN"
  value       = aws_rds_cluster.database.arn
}

output "database_name" {
  description = "Database name"
  value       = aws_rds_cluster.database.database_name
}

output "database_url" {
  description = "Full PostgreSQL connection string"
  value       = "postgresql://${var.db_user}:${var.db_password}@${aws_rds_cluster.database.endpoint}:5432/${var.db_name}"
  sensitive   = true
}

output "security_group_id" {
  description = "Security group ID for database"
  value       = aws_security_group.database.id
}
