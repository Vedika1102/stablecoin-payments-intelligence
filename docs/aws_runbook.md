# Running the project on AWS

Everything is deployed by GitHub Actions through a short-lived OIDC role, so no AWS access keys
are ever created or stored. Expected cost for the full exercise: about $10 to $25, all inside
the new-account credits.

| Step | Who | Where | Time |
|---|---|---|---|
| 1. Upgrade to the paid plan (Redshift isn't on the free plan; credits still apply) | you | AWS console > Billing | 2 min |
| 2. Budget alarm at $5 | you | AWS console > Budgets | 3 min |
| 3. Bootstrap stack (deploy role + Terraform state) | you | AWS console > CloudFormation | 5 min |
| 4. Repository variables | either | GitHub > Settings > Variables | 2 min |
| 5. `deploy` workflow (Terraform apply, Glue code upload) | GitHub | Actions | ~5 min |
| 6. `run-pipeline` workflow (two-year Glue backfill) | GitHub | Actions | ~1 to 2 h |
| 7. `warehouse` workflow (Spectrum schemas + dbt build on Redshift) | GitHub | Actions | ~20 min |
| 8. Hands-on lab in Query Editor v2 (`warehouse/redshift/06_hands_on_lab.sql`) | you | AWS console > Redshift | 1 to 2 h |
| 9. Turn Redshift off (`ENABLE_REDSHIFT=false`, re-run deploy) or `teardown` | either | Actions | ~5 min |

## 1. Upgrade
Billing and Cost Management > upgrade your plan to Paid. Remaining credits keep applying.

## 2. Budget
Billing and Cost Management > Budgets > Create budget > *Use a template* > **Monthly cost budget**,
amount **$5**, your email. AWS emails you at 85% and 100% of it.

## 3. Bootstrap stack
1. Region selector (top right): **US East (Ohio) us-east-2**.
2. CloudFormation > Create stack > *With new resources* > *Upload a template file* >
   `infra/bootstrap/github-oidc.yaml` from this repo.
3. Stack name `stablecoin-bootstrap`. Keep the defaults. (If the account already has a GitHub OIDC
   provider, set `CreateOidcProvider` to `false`.)
4. Tick "I acknowledge that AWS CloudFormation might create IAM resources with custom names" > Submit.
5. When it shows `CREATE_COMPLETE`, open the **Outputs** tab and copy `DeployRoleArn` and `StateBucket`.

## 4. Repository variables (GitHub > Settings > Secrets and variables > Actions > Variables)
| Variable | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `DeployRoleArn` from step 3 |
| `TF_STATE_BUCKET` | `StateBucket` from step 3 |
| `ENABLE_REDSHIFT` | `true` |
| `ALERT_EMAIL` | where pipeline alerts go (confirm the SNS subscription email) |

## 5 to 7. Workflows (GitHub > Actions)
* **deploy** runs on push or by hand. Creates the S3 lake, Glue jobs and catalog, Athena workgroup,
  Step Functions + EventBridge schedule, SNS/CloudWatch alarms and Redshift Serverless (8 RPU,
  capped at 32 RPU-hours a month).
* **run-pipeline**: *Run workflow* with start `2023-07-01`, end `2025-06-30`. Prints Glue run time and
  DPU-seconds per job (the cost evidence for the README).
* **warehouse**: builds the Redshift warehouse with dbt and runs all tests on Redshift.

## 8. Hands-on lab
Redshift > Query editor v2 > connect to workgroup `stablecoin-payments-dev`, database `analytics`
(federated user). Open `warehouse/redshift/02_core_tables.sql` and `03_load_procedure.sql`, run them,
then work through `06_hands_on_lab.sql` block by block. Screenshot: the Spectrum scan summary, the
COPY load audit and reconciliation, both EXPLAIN plans (DS_DIST_NONE vs DS_BCAST), `svv_table_info`,
and the RPU-hours query.

## 9. Stop paying
* Keep the lake, drop Redshift: set `ENABLE_REDSHIFT=false`, re-run **deploy**.
* Delete everything: run **teardown** and type `DESTROY`. Then delete the `stablecoin-bootstrap`
  stack (empty the state bucket first if CloudFormation asks).
* Also stop the daily schedule if you don't want it: EventBridge > Rules > `stablecoin-payments-dev-daily` > Disable.
