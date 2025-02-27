resource "google_storage_bucket" "bucket" {
  name          = var.bucket_name
  location      = data.google_client_config.current.region
  encryption {
    default_kms_key_name = data.google_kms_crypto_key.kms.id
  }
  force_destroy = true
}

resource "google_storage_bucket_acl" "acl" {
  bucket = google_storage_bucket.bucket.name

  predefined_acl = var.block_public ? "private" : "publicRead"
}