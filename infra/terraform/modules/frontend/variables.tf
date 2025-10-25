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
