resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${local.prefix}-daily"
  retention_in_days = 30
}

resource "aws_sfn_state_machine" "daily" {
  name     = "${local.prefix}-daily"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/../../aws/stepfunctions/daily_pipeline.asl.json", {
    ingest_job   = aws_glue_job.pipeline["ingest_bronze"].name
    silver_job   = aws_glue_job.pipeline["build_silver"].name
    gold_job     = aws_glue_job.pipeline["build_gold"].name
    workgroup    = var.enable_redshift ? aws_redshiftserverless_workgroup.this[0].workgroup_name : "disabled"
    database     = var.enable_redshift ? aws_redshiftserverless_namespace.this[0].db_name : "disabled"
    after_gold   = var.enable_redshift ? "LoadRedshift" : "Succeeded"
    alerts_topic = aws_sns_topic.alerts.arn
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }
}

# The public dataset publishes the previous UTC day by ~01:00 UTC; run at 03:00 UTC.
resource "aws_cloudwatch_event_rule" "daily" {
  name                = "${local.prefix}-daily"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "daily" {
  rule     = aws_cloudwatch_event_rule.daily.name
  arn      = aws_sfn_state_machine.daily.arn
  role_arn = aws_iam_role.events.arn
}
