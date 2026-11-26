locals {
  prefix = "${var.project}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# One bucket for the lake (bronze/silver/gold/_dq_results), one for code + Athena results.
resource "aws_s3_bucket" "lake" {
  bucket = "${local.prefix}-lake-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${local.prefix}-artifacts-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { lake = aws_s3_bucket.lake.id, artifacts = aws_s3_bucket.artifacts.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = { lake = aws_s3_bucket.lake.id, artifacts = aws_s3_bucket.artifacts.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Cost control: bronze is re-derivable from the public source, so it ages out to cheaper storage;
# Athena query results are temporary.
resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    id     = "bronze-to-ia"
    status = "Enabled"
    filter {
      prefix = "bronze/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
  rule {
    id     = "abort-mpu"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter {
      prefix = "athena-results/"
    }
    expiration {
      days = 14
    }
  }
}

# Pipeline code: the lakehouse package zipped by CI, plus Glue entry scripts
resource "aws_s3_object" "glue_entrypoints" {
  for_each = fileset("${path.module}/../../aws/glue", "*.py")
  bucket   = aws_s3_bucket.artifacts.id
  key      = "glue/${each.value}"
  source   = "${path.module}/../../aws/glue/${each.value}"
  etag     = filemd5("${path.module}/../../aws/glue/${each.value}")
}
