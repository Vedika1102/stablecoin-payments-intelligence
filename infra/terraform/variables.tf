variable "project" {
  type    = string
  default = "stablecoin-payments"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "us-east-2"
}

variable "alert_email" {
  description = "Where pipeline failure and data quality alerts are sent."
  type        = string
  default     = ""
}

variable "glue_worker_type" {
  type    = string
  default = "G.1X"
}

variable "glue_workers" {
  description = "Workers per Glue job. A month of transfers fits comfortably in 10 G.1X workers."
  type        = number
  default     = 10
}

variable "redshift_base_rpu" {
  description = "Redshift Serverless base capacity. 8 RPU is the minimum and plenty for this mart."
  type        = number
  default     = 8
}

variable "athena_bytes_scanned_cutoff" {
  description = "Per-query scan limit for the analyst workgroup (cost guardrail). 200 GB."
  type        = number
  default     = 214748364800
}

variable "enable_redshift" {
  description = "Create Redshift Serverless and the load step. Off by default: the AWS free account plan does not include Redshift."
  type        = bool
  default     = false
}

variable "redshift_monthly_rpu_hours_cap" {
  description = "Hard monthly cap on Redshift Serverless compute. At 8 RPU and about $0.375 per RPU-hour, 32 RPU-hours is about $12; the workgroup is deactivated when it is hit."
  type        = number
  default     = 32
}
