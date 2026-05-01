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
    Name = "${var.project_name}-apprunner-access-role"
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
    Name = "${var.project_name}-apprunner-instance-role"
  }
}

# secrets-access: OpenAI only (matches live prod shape — split per-secret policies)
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
      ]
    }]
  })
}

resource "aws_iam_role_policy" "app_runner_anthropic_secret" {
  count = var.anthropic_secret_arn != "" ? 1 : 0
  name  = "anthropic-secret-access"
  role  = aws_iam_role.app_runner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = var.anthropic_secret_arn
    }]
  })
}

resource "aws_iam_role_policy" "app_runner_elevenlabs_secret" {
  count = var.elevenlabs_secret_arn != "" ? 1 : 0
  name  = "elevenlabs-secret-access"
  role  = aws_iam_role.app_runner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = var.elevenlabs_secret_arn
    }]
  })
}

resource "aws_iam_role_policy" "app_runner_cognito" {
  name = "cognito-admin"
  role = aws_iam_role.app_runner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cognito-idp:AdminGetUser",
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminSetUserPassword",
        "cognito-idp:AdminDeleteUser",
      ]
      Resource = "arn:aws:cognito-idp:${var.cognito_region}:${data.aws_caller_identity.current.account_id}:userpool/${var.cognito_user_pool_id}"
    }]
  })
}

data "aws_caller_identity" "current" {}

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
    Name = "${var.project_name}-autoscaling"
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
          API_HOST                 = "0.0.0.0"
          API_PORT                 = "8000"
          COGNITO_APP_CLIENT_ID    = var.cognito_app_client_id
          COGNITO_REGION           = var.cognito_region
          COGNITO_USER_POOL_ID     = var.cognito_user_pool_id
          DATABASE_URL             = var.database_url
          ENVIRONMENT              = var.environment
          GOOGLE_CLOUD_TTS_API_KEY = var.google_cloud_tts_api_key
          LLM_MODEL                = var.llm_model
          TTS_PROVIDER             = var.tts_provider
          TUTOR_LLM_PROVIDER       = var.tutor_llm_provider
        }

        runtime_environment_secrets = merge(
          {
            OPENAI_API_KEY = var.openai_secret_arn
          },
          var.anthropic_secret_arn != "" ? {
            ANTHROPIC_API_KEY = var.anthropic_secret_arn
          } : {},
          var.elevenlabs_secret_arn != "" ? {
            ELEVENLABS_API_KEY = var.elevenlabs_secret_arn
          } : {}
        )
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

  # Network configuration: provisioned instances for background job support.
  # Background threads (guidelines extraction, bulk OCR) need continuous CPU
  # between HTTP requests. Request-driven mode throttles CPU when idle.
  # Cost: ~$25/mo per always-on instance (acceptable for admin tool).
  network_configuration {
    ingress_configuration {
      is_publicly_accessible = true
    }
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  tags = {
    Name = "${var.project_name}-backend"
  }
}
