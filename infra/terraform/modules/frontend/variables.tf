variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "api_endpoint_url" {
  description = "Backend API endpoint URL for CORS configuration"
  type        = string
}
