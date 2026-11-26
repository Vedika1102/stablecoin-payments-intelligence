output "lake_bucket" { value = aws_s3_bucket.lake.bucket }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "athena_workgroup" { value = aws_athena_workgroup.analysts.name }
output "redshift_workgroup" { value = one(aws_redshiftserverless_workgroup.this[*].workgroup_name) }
output "redshift_spectrum_role_arn" { value = aws_iam_role.redshift.arn }
output "state_machine_arn" { value = aws_sfn_state_machine.daily.arn }
output "glue_catalog_lake_db" { value = aws_glue_catalog_database.lake.name }
