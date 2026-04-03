# RDS PostgreSQL Instance

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
    cidr_blocks = ["0.0.0.0/0"] # In production, restrict to App Runner security group
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

# Subnet Group
resource "aws_db_subnet_group" "database" {
  name       = "${var.project_name}-database-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.project_name}-database-subnet-group"
    Environment = var.environment
  }
}

# DB Parameter Group
resource "aws_db_parameter_group" "database" {
  name        = "${var.project_name}-rds-pg-${var.environment}"
  family      = "postgres15"
  description = "DB parameter group for ${var.project_name}"

  tags = {
    Name        = "${var.project_name}-db-parameter-group"
    Environment = var.environment
  }
}

# RDS PostgreSQL Instance (free tier eligible)
resource "aws_db_instance" "database" {
  identifier     = "${var.project_name}-${var.environment}"
  engine         = "postgres"
  engine_version = "15"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp2"

  db_name  = var.db_name
  username = var.db_user
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.database.name
  parameter_group_name   = aws_db_parameter_group.database.name
  vpc_security_group_ids = [aws_security_group.database.id]

  publicly_accessible = true # Set to false in production with VPC peering

  # Backup and maintenance
  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:00-mon:05:00"

  # Deletion protection
  deletion_protection = false
  skip_final_snapshot = true

  tags = {
    Name        = "${var.project_name}-rds-instance"
    Environment = var.environment
  }
}
