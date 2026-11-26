resource "aws_athena_workgroup" "analysts" {
  name          = "${local.prefix}-analysts"
  force_destroy = true
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff # cost guardrail
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
    result_configuration {
      output_location = "s3://${aws_s3_bucket.artifacts.bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

resource "aws_athena_named_query" "saved" {
  for_each  = fileset("${path.module}/../../aws/athena", "*.sql")
  name      = trimsuffix(each.value, ".sql")
  workgroup = aws_athena_workgroup.analysts.id
  database  = aws_glue_catalog_database.lake.name
  query     = file("${path.module}/../../aws/athena/${each.value}")
}
