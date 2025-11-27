# AWS App Runner for Backend Container Service

# IAM Role for App Runner to access ECR and Secrets Manager
resource "aws_iam_role" "app_runner_access" {
  name = "${var.project_name}-apprunner-access-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "build.apprunner.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = "${var.project_name}-apprunner-access-role"
    Environment = var.environment
  }
}

# Policy to allow App Runner to pull from ECR
resource "aws_iam_role_policy_attachment" "app_runner_ecr" {
  role       = aws_iam_role.app_runner_access.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# IAM Role for App Runner Instance (runtime)
resource "aws_iam_role" "app_runner_instance" {
  name = "${var.project_name}-apprunner-instance-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "tasks.apprunner.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = "${var.project_name}-apprunner-instance-role"
    Environment = var.environment
  }
}

# Policy to allow App Runner to read secrets
resource "aws_iam_role_policy" "app_runner_secrets" {
  name = "secrets-access"
  role = aws_iam_role.app_runner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = [
        var.openai_secret_arn,
        var.gemini_secret_arn
      ]
    }]
  })
}

# Policy to allow App Runner to access S3 for book ingestion
resource "aws_iam_role_policy" "app_runner_s3_books" {
  name = "s3-books-access"
  role = aws_iam_role.app_runner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        "arn:aws:s3:::${var.s3_books_bucket}",
        "arn:aws:s3:::${var.s3_books_bucket}/*"
      ]
    }]
  })
}

# App Runner Auto Scaling Configuration
resource "aws_apprunner_auto_scaling_configuration_version" "backend" {
  auto_scaling_configuration_name = "llm-autoscale-${var.environment}"

  max_concurrency = 100
  max_size        = 5
  min_size        = 1

  tags = {
    Name        = "${var.project_name}-autoscaling"
    Environment = var.environment
  }
}

# App Runner Service
resource "aws_apprunner_service" "backend" {
  service_name = "llm-backend-prod"

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.app_runner_access.arn
    }

    image_repository {
      image_identifier      = "${var.ecr_repository_url}:latest"
      image_repository_type = "ECR"

      image_configuration {
        port = "8000"

        runtime_environment_variables = {
          API_HOST     = "0.0.0.0"
          API_PORT     = "8000"
          DATABASE_URL = var.database_url
          LLM_MODEL    = var.llm_model
          ENVIRONMENT  = var.environment
        }

        runtime_environment_secrets = {
          OPENAI_API_KEY = var.openai_secret_arn
          GEMINI_API_KEY = var.gemini_secret_arn
        }
      }
    }

    auto_deployments_enabled = false # Manual deployments via GitHub Actions
  }

  instance_configuration {
    cpu               = "1 vCPU"
    memory            = "2 GB"
    instance_role_arn = aws_iam_role.app_runner_instance.arn
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.backend.arn

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  tags = {
    Name        = "${var.project_name}-backend"
    Environment = var.environment
  }
}
