# Redshift is not available on the AWS free account plan, so it is opt-in (var.enable_redshift).
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "redshift" {
  count       = var.enable_redshift ? 1 : 0
  name        = "${local.prefix}-redshift"
  description = "Redshift Serverless. No inbound rules at rest; CI adds its runner IP temporarily."
  vpc_id      = data.aws_vpc.default.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle {
    ignore_changes = [ingress] # temporary CI rules are managed by the workflow
  }
}

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
  count          = var.enable_redshift ? 1 : 0
  namespace_name = aws_redshiftserverless_namespace.this[0].namespace_name
  workgroup_name = local.prefix
  base_capacity  = var.redshift_base_rpu
  # Reachable from outside the VPC only through the security group below, which has no inbound
  # rules by default. The warehouse workflow opens port 5439 to its own runner IP for the run.
  publicly_accessible = true
  subnet_ids          = data.aws_subnets.default.ids
  security_group_ids  = [aws_security_group.redshift[0].id]
  config_parameter {
    parameter_key   = "enable_user_activity_logging"
    parameter_value = "true"
  }
  config_parameter {
    parameter_key   = "max_query_execution_time"
    parameter_value = "3600"
  }
  lifecycle {
    # The API echoes back every default parameter (auto_mv, datestyle, ...), which the provider
    # reports as a diff on each plan and then fails to "update". Ours are set at creation.
    ignore_changes = [config_parameter]
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
