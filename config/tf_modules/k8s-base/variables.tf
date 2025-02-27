data "aws_region" "current" {}

locals {
  target_ports = var.cert_arn == "" ? { http: "http" } : { http: "http", https: "https" }
  container_ports = var.cert_arn == "" ? { http: 80, https: 443 } : { http: 80, https: 443 }
  config = var.cert_arn == "" ? { ssl-redirect: false } : {
    ssl-redirect: false
    server-snippet: <<EOF
          if ( $server_port = 80 ) {
             return 308 https://$host$request_uri;
          }
          EOF
  }
}

variable "eks_cluster_name" {
  type = string
}

variable "env_name" {
  description = "Env name"
  type = string
}

variable "layer_name" {
  description = "Layer name"
  type        = string
}

variable "module_name" {
  description = "Module name"
  type = string
}

variable "domain" {
  type = string
  default = ""
}

variable "cert_arn" {
  type = string
  default = ""
}

variable "openid_provider_url" {
  type = string
}

variable "openid_provider_arn" {
  type = string
}

variable "high_availability" {
  type = bool
  default = true
}

variable "admin_arns" {
  type = list(string)
  default = []
}
