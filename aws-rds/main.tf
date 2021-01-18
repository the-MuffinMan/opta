resource "random_password" "pg_password" {
  length = 20
}

data "aws_db_subnet_group" "subnet_group" {
  count = var.subnet_group_name == "" ? 1 : 0
  name = "main"
}

data "aws_security_group" "security_group" {
  count = var.security_group == "" ? 1 : 0
  name = "db-sg"
}

resource "aws_rds_cluster" "db_cluster" {
  cluster_identifier = var.name
  db_subnet_group_name = var.subnet_group_name
  database_name = "app"
  engine = var.engine
  engine_version = var.engine_version
  master_username = "postgres"
  master_password = random_password.pg_password.result
}

resource "aws_rds_cluster_instance" "db_instance" {
  count = 1
  identifier         = "${var.name}-${count.index}"
  cluster_identifier = aws_rds_cluster.db_cluster.id
  instance_class     = var.instance_class
  engine             = aws_rds_cluster.db_cluster.engine
  engine_version     = aws_rds_cluster.db_cluster.engine_version
}