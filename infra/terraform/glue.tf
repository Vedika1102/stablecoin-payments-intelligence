# ---------------------------------------------------------------------------------------------
# Glue Data Catalog
#   public_eth : external tables over the AWS Public Blockchain bucket, with partition projection
#                so Athena/Spectrum can prune by date without crawlers or MSCK REPAIR.
#   lake       : our bronze/silver/gold tables (registered by the Glue jobs / crawler below).
# ---------------------------------------------------------------------------------------------
resource "aws_glue_catalog_database" "public_eth" {
  name = replace("${local.prefix}_public_eth", "-", "_")
}

resource "aws_glue_catalog_database" "lake" {
  name = replace("${local.prefix}_lake", "-", "_")
}

locals {
  projection_params = {
    "projection.enabled"            = "true"
    "projection.date.type"          = "date"
    "projection.date.format"        = "yyyy-MM-dd"
    "projection.date.range"         = "2015-07-30,NOW"
    "projection.date.interval"      = "1"
    "projection.date.interval.unit" = "DAYS"
    "classification"                = "parquet"
  }
}

resource "aws_glue_catalog_table" "token_transfers" {
  database_name = aws_glue_catalog_database.public_eth.name
  name          = "token_transfers"
  table_type    = "EXTERNAL_TABLE"
  parameters = merge(local.projection_params, {
    "storage.location.template" = "s3://aws-public-blockchain/v1.0/eth/token_transfers/date=$${date}/"
  })
  partition_keys {
    name = "date"
    type = "string"
  }
  storage_descriptor {
    location      = "s3://aws-public-blockchain/v1.0/eth/token_transfers/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    dynamic "columns" {
      for_each = {
        token_address    = "string", from_address = "string", to_address = "string", value = "double",
        transaction_hash = "string", log_index = "bigint", block_number = "bigint", block_hash = "string",
        block_timestamp  = "timestamp", last_modified = "timestamp"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_glue_catalog_table" "blocks" {
  database_name = aws_glue_catalog_database.public_eth.name
  name          = "blocks"
  table_type    = "EXTERNAL_TABLE"
  parameters = merge(local.projection_params, {
    "storage.location.template" = "s3://aws-public-blockchain/v1.0/eth/blocks/date=$${date}/"
  })
  partition_keys {
    name = "date"
    type = "string"
  }
  storage_descriptor {
    location      = "s3://aws-public-blockchain/v1.0/eth/blocks/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    dynamic "columns" {
      for_each = {
        number   = "bigint", hash = "string", timestamp = "timestamp", base_fee_per_gas = "bigint",
        gas_used = "bigint", gas_limit = "bigint", transaction_count = "bigint", last_modified = "timestamp"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

# Crawler keeps the lake tables' schemas and partitions registered after each run
resource "aws_glue_crawler" "lake" {
  name          = "${local.prefix}-lake"
  role          = aws_iam_role.glue.arn
  database_name = aws_glue_catalog_database.lake.name
  dynamic "s3_target" {
    for_each = ["silver/stablecoin_transfers", "gold/daily_kpis", "gold/hourly_activity", "gold/hourly_network",
    "gold/wallet_daily", "gold/wallet_monthly", "gold/wallet_profile", "_dq_results"]
    content {
      path = "s3://${aws_s3_bucket.lake.bucket}/${s3_target.value}/"
    }
  }
  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
  recrawl_policy {
    recrawl_behavior = "CRAWL_EVERYTHING" # required for UPDATE_IN_DATABASE schema changes
  }
}

# ---------------------------------------------------------------------------------------------
# Glue 5.0 (Spark 3.5) jobs. Same code as local: the lakehouse package ships as a zip.
# ---------------------------------------------------------------------------------------------
locals {
  glue_jobs = {
    ingest_bronze           = { script = "ingest_bronze.py", workers = var.glue_workers }
    build_contract_registry = { script = "build_contract_registry.py", workers = var.glue_workers }
    build_silver            = { script = "build_silver.py", workers = var.glue_workers }
    build_gold              = { script = "build_gold.py", workers = var.glue_workers * 2 }
  }
}

resource "aws_glue_job" "pipeline" {
  for_each          = local.glue_jobs
  name              = "${local.prefix}-${each.key}"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = var.glue_worker_type
  number_of_workers = each.value.workers
  timeout           = 120
  max_retries       = 1
  execution_property {
    max_concurrent_runs = 1 # one writer per table: avoids partition overwrite races
  }
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.artifacts.bucket}/glue/${each.value.script}"
  }
  default_arguments = {
    "--extra-py-files"                   = "s3://${aws_s3_bucket.artifacts.bucket}/dist/lakehouse.zip"
    "--extra-files"                      = "s3://${aws_s3_bucket.artifacts.bucket}/dist/tokens.csv"
    "--SOURCE_ROOT"                      = "s3://aws-public-blockchain/v1.0/eth"
    "--LAKE_ROOT"                        = "s3://${aws_s3_bucket.lake.bucket}"
    "--enable-metrics"                   = "true"
    "--enable-observability-metrics"     = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-spark-ui"                  = "true"
    "--spark-event-logs-path"            = "s3://${aws_s3_bucket.artifacts.bucket}/spark-events/"
    "--job-bookmark-option"              = "job-bookmark-disable" # idempotency handled by partition overwrite
    "--conf"                             = "spark.sql.sources.partitionOverwriteMode=dynamic"
  }
}

# Glue Data Quality ruleset on the silver table (DQDL), evaluated after build_silver
resource "aws_glue_data_quality_ruleset" "silver_transfers" {
  name        = "${local.prefix}-silver-transfers"
  description = "Silver stablecoin transfers: completeness, uniqueness, validity"
  ruleset     = file("${path.module}/../../aws/glue/dq_rules_silver.dqdl")
  # No target_table: the catalog table only exists after the first crawl. The evaluation run
  # (Airflow GlueDataQualityRuleSetEvaluationRunOperator) names the table it checks.
}
