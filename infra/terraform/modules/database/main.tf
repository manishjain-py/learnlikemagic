# Aurora Serverless v2 PostgreSQL Cluster

# Security Group for Database
resource "aws_security_group" "database" {
  name        = "${var.project_name}-database-${var.environment}"
  description = "Security group for Aurora database"
  vpc_id      = var.vpc_id

  ingress {
    description = "PostgreSQL from VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # In production, restrict to App Runner security group
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-database-sg"
    Environment = var.environment
  }
}

# Subnet Group for Aurora
resource "aws_db_subnet_group" "database" {
  name       = "${var.project_name}-database-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.project_name}-database-subnet-group"
    Environment = var.environment
  }
}

# Aurora Cluster Parameter Group
resource "aws_rds_cluster_parameter_group" "database" {
  name        = "${var.project_name}-cluster-pg-${var.environment}"
  family      = "aurora-postgresql15"
  description = "Cluster parameter group for ${var.project_name}"

  parameter {
    name  = "timezone"
    value = "UTC"
  }

  tags = {
    Name        = "${var.project_name}-cluster-parameter-group"
    Environment = var.environment
  }
}

# Aurora DB Parameter Group
resource "aws_db_parameter_group" "database" {
  name        = "${var.project_name}-db-pg-${var.environment}"
  family      = "aurora-postgresql15"
  description = "DB parameter group for ${var.project_name}"

  tags = {
    Name        = "${var.project_name}-db-parameter-group"
    Environment = var.environment
  }
}

# Aurora Serverless v2 Cluster
resource "aws_rds_cluster" "database" {
  cluster_identifier     = "${var.project_name}-${var.environment}"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  engine_version         = "15.10"
  database_name          = var.db_name
  master_username        = var.db_user
  master_password        = var.db_password

  db_subnet_group_name            = aws_db_subnet_group.database.name
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.database.name
  vpc_security_group_ids          = [aws_security_group.database.id]

  # Serverless v2 scaling configuration
  serverlessv2_scaling_configuration {
    max_capacity = 2.0  # 2 ACUs
    min_capacity = 0.5  # 0.5 ACUs (minimum)
  }

  # Backup and maintenance
  backup_retention_period = 7
  preferred_backup_window = "03:00-04:00"
  preferred_maintenance_window = "mon:04:00-mon:05:00"

  # Deletion protection (set to true in production)
  deletion_protection = false
  skip_final_snapshot = true  # Set to false in production
  # final_snapshot_identifier = "${var.project_name}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = {
    Name        = "${var.project_name}-aurora-cluster"
    Environment = var.environment
  }
}

# Aurora Serverless v2 Instance
resource "aws_rds_cluster_instance" "database" {
  identifier              = "${var.project_name}-instance-${var.environment}"
  cluster_identifier      = aws_rds_cluster.database.id
  instance_class          = "db.serverless"
  engine                  = aws_rds_cluster.database.engine
  engine_version          = aws_rds_cluster.database.engine_version
  db_parameter_group_name = aws_db_parameter_group.database.name

  publicly_accessible = true  # Set to false in production with VPC peering

  tags = {
    Name        = "${var.project_name}-aurora-instance"
    Environment = var.environment
  }
}
