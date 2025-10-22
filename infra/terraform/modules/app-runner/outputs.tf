output "service_url" {
  description = "App Runner service URL"
  value       = "https://${aws_apprunner_service.backend.service_url}"
}

output "service_arn" {
  description = "App Runner service ARN"
  value       = aws_apprunner_service.backend.arn
}

output "service_id" {
  description = "App Runner service ID"
  value       = aws_apprunner_service.backend.service_id
}

output "service_status" {
  description = "App Runner service status"
  value       = aws_apprunner_service.backend.status
}
