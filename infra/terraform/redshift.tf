# Redshift is not available on the AWS free account plan, so it is opt-in (var.enable_redshift).
resource "aws_redshiftserverless_namespace" "this" {
  count                 = var.enable_redshift ? 1 : 0
  namespace_name        = local.prefix
  db_name               = "analytics"
  admin_username        = "admin"
  manage_admin_password = true # password lives in Secrets Manager, never in state or code
  iam_roles             = [aws_iam_role.redshift.arn]
  default_iam_role_arn  = aws_iam_role.redshift.arn
  log_exports           = ["userlog", "connectionlog", "useractivitylog"]
}

resource "aws_redshiftserverless_workgroup" "this" {
  count               = var.enable_redshift ? 1 : 0
  namespace_name      = aws_redshiftserverless_namespace.this[0].namespace_name
  workgroup_name      = local.prefix
  base_capacity       = var.redshift_base_rpu
  publicly_accessible = false
  config_parameter {
    parameter_key   = "enable_user_activity_logging"
    parameter_value = "true"
  }
  config_parameter {
    parameter_key   = "max_query_execution_time"
    parameter_value = "3600"
  }
}

# Cost guardrail: cap monthly RPU-hours
resource "aws_redshiftserverless_usage_limit" "rpu" {
  count         = var.enable_redshift ? 1 : 0
  resource_arn  = aws_redshiftserverless_workgroup.this[0].arn
  usage_type    = "serverless-compute"
  amount        = var.redshift_monthly_rpu_hours_cap
  period        = "monthly"
  breach_action = "deactivate"
}
