# Stablecoin Payments Intelligence

An end-to-end analytics platform on **real public data**: every USDC, USDT, DAI and PYUSD transfer on
Ethereum for two years (Jul 2023 to Jun 2025), read straight from the
[AWS Public Blockchain dataset](https://registry.opendata.aws/aws-public-blockchain/) in S3.

**Business questions**
1. How much stablecoin activity is actually payments, and who carries it (USDC vs USDT, which wallet segments)?
2. How sensitive are small payments to network fees?
3. Did the Dencun upgrade (cheaper rollups, March 2024) pull small payments off mainnet?
4. How do new wallets activate and retain, and what predicts retention?

**Headline findings** (full memo: [`docs/findings_memo.md`](docs/findings_memo.md))
* Wallet-to-wallet transfers under $1K are **27.7% of transfers but 0.07% of value**.
* Small payments have a fee elasticity of **-0.149** (95% CI -0.163 to -0.135), **0.24 more elastic** than large ones.
* **80% of "activated" new wallets are pass-through** addresses with 5% 60-day activity. Pooling them flips the sign
  of activation's effect on retention (odds ratio 0.55 without the control, 1.51 with it).
* A tempting Dencun causal story **fails** its placebo and pre-trend checks, and the memo says so.
* Found and removed **11.9M address-poisoning spam transfers** that would have inflated small-payment counts.

## Scale
| | |
|---|---|
| Source rows scanned (all ERC-20 transfers) | **1.01 billion** |
| Stablecoin transfers in silver | **215 million** ($19.8 trillion) |
| Contract registry (all contracts ever created) | 78.6 million addresses |
| Wallet x day / wallet x month / wallets | 85.6M / 42.4M / 23.9M rows |
| Automated DQ checks | 717 lake checks + 63 dbt models and tests, all passing |

Details: [`reports/pipeline_run.md`](reports/pipeline_run.md).

## Architecture
See [`docs/architecture.md`](docs/architecture.md) for the diagram and design decisions.

```
S3 public data ──► PySpark on Glue: bronze ─► silver ─► gold  (DQ results on every layer)
                                         │
             Glue Catalog + Athena ◄─────┤
                                         ▼
                 Redshift Serverless (Spectrum + COPY) ─► dbt core + marts ─► Tableau / Python stats
Orchestration: Step Functions + EventBridge (or MWAA DAG) · IaC: Terraform · CI/CD: GitHub Actions
```

## How this maps to the BIE role
| Skill | Where it lives |
|---|---|
| Big data / PySpark | `lakehouse/jobs/`: medallion lake, partition pruning on S3, broadcast and semi-joins, dynamic partition overwrite, month-by-month builds |
| AWS integration | `infra/terraform/`: S3, IAM, Glue jobs + catalog + Data Quality, Athena, Redshift Serverless, Step Functions, EventBridge, SNS, CloudWatch |
| Redshift | `warehouse/redshift/`: star schema with DISTKEY/SORTKEY choices, Spectrum external schemas, COPY load procedure, materialized view, monitoring queries |
| Data modeling | `dbt/`: SCD2 wallet dimension (gaps-and-islands), conformed date/token dims, facts at three grains, marts, custom generic tests |
| SQL | Window functions, QUALIFY, NTILE, as-of joins, reconciliation tests (`warehouse/redshift/04_analytical_queries.sql`, dbt models) |
| Statistics | `analysis/`: log-log regression with HAC errors and fixed effects, difference-in-differences with event study and placebo, chi-squared + Cramér's V, two-proportion tests, logistic regression, Kaplan-Meier + log-rank |
| BI | `tableau/BUILD_GUIDE.md` and `tableau/extracts/` (Tableau Public, six dashboards) |
| Data quality | `lakehouse/dq.py`, Glue DQDL rules, dbt tests, a DQ dashboard |
| Analytics as software | `.github/workflows/`: lint, unit tests, terraform validate, a smoke run on real data, OIDC deploy |

## Run it
Local runs read the public bucket anonymously, so no AWS account is needed.

```bash
make setup                          # Python deps + hadoop-aws jars for s3a
make test                           # unit tests (Spark + stats)
make lake START=2024-03-01 END=2024-03-31   # one month: bronze, contract registry, silver, gold
make warehouse                      # dbt build on DuckDB (dev target)
make analysis extracts              # reports/*.md, figures, Tableau CSVs
python scripts/pipeline_report.py   # reports/pipeline_run.md
```

The full two-year backfill took about 3 hours on a 4-core, 16 GB machine (`scripts/run_backfill.sh`).
On AWS: `terraform apply` in `infra/terraform`, upload the package (`make package`), then start the
Step Functions state machine with a backfill input. Roughly $9 of Glue for the full window.

## Repository layout
```
lakehouse/        PySpark jobs, transforms, DQ framework (runs locally or on Glue)
aws/              Glue entry points, DQDL rules, Step Functions definition, Athena queries
infra/terraform/  all AWS resources
orchestration/    Airflow (MWAA) DAG, alternative to Step Functions
warehouse/redshift/  DDL, load procedure, analytical and monitoring SQL
dbt/              staging, core (star schema, SCD2), marts, tests
analysis/         statistics, figures, report generation, Tableau extracts
reports/          generated reports and figures
docs/             architecture, metric definitions, findings memo, interview notes
tests/            unit tests
```

## Limitations
Mainnet only (rollups are outside the dataset). All four tokens valued at $1. Wallets are addresses, not
people. Fees exclude the priority tip. Segment thresholds are documented judgment calls.
