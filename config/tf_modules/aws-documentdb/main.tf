resource "random_password" "documentdb_auth" {
  length = 20
  special = false
}

data "aws_security_group" "security_group" {
  name = "opta-${var.env_name}-documentdb-sg"
}

data "aws_kms_key" "main" {
  key_id = "alias/opta-${var.env_name}"
}

resource "aws_docdb_cluster_instance" "cluster_instances" {
  count              = 1
  identifier         = "opta-${var.layer_name}-${var.module_name}-${count.index}"
  cluster_identifier = aws_docdb_cluster.cluster.id
  instance_class     = var.instance_class
  apply_immediately = true
  auto_minor_version_upgrade = true
}

resource "aws_docdb_cluster" "cluster" {
  cluster_identifier = "opta-${var.layer_name}-${var.module_name}"
  master_username    = "master_user"
  master_password    = random_password.documentdb_auth.result
  db_subnet_group_name = "opta-${var.env_name}-docdb"
  engine_version = var.engine_version
  storage_encrypted = true
  kms_key_id = data.aws_kms_key.main.arn
  vpc_security_group_ids = [data.aws_security_group.security_group.id]
  backup_retention_period = 5
  apply_immediately = true
  skip_final_snapshot = true
}
