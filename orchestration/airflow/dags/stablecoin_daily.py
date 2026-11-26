"""
Airflow (Amazon MWAA) version of the daily pipeline. Step Functions is the default orchestrator
in Terraform; this DAG is the equivalent for teams standardised on Airflow.

  wait for public partition -> Glue bronze -> Glue silver -> Glue DQ ruleset -> Glue gold
  -> crawler -> Redshift load procedure -> dbt build (prod) -> dbt tests

Backfills: `airflow dags backfill stablecoin_daily -s 2024-01-01 -e 2024-01-31`. Each task is
idempotent for its logical date (dynamic partition overwrite), so reruns are safe.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.amazon.aws.operators.glue import GlueDataQualityRuleSetEvaluationRunOperator, GlueJobOperator
from airflow.providers.amazon.aws.operators.glue_crawler import GlueCrawlerOperator
from airflow.providers.amazon.aws.operators.redshift_data import RedshiftDataOperator
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor

ENV = "dev"
PREFIX = f"stablecoin-payments-{ENV}"
DS = "{{ ds }}"  # logical date = the day being processed

default_args = {
    "owner": "bie",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "sla": timedelta(hours=4),
}

with DAG(
    dag_id="stablecoin_daily",
    start_date=datetime(2023, 7, 1),
    schedule="0 3 * * *",
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["stablecoin", "glue", "redshift"],
) as dag:
    wait_for_source = S3KeySensor(
        task_id="wait_for_public_partition",
        bucket_name="aws-public-blockchain",
        bucket_key=f"v1.0/eth/token_transfers/date={DS}/*.parquet",
        wildcard_match=True,
        mode="reschedule",          # frees the worker slot while waiting
        poke_interval=900,
        timeout=60 * 60 * 12,
    )

    def glue(job: str, dated: bool = True) -> GlueJobOperator:
        return GlueJobOperator(
            task_id=job,
            job_name=f"{PREFIX}-{job}",
            script_args={"--start": DS, "--end": DS} if dated else {},
            wait_for_completion=True,
            verbose=False,
        )

    bronze, silver, gold = glue("ingest_bronze"), glue("build_silver"), glue("build_gold", dated=False)

    glue_dq = GlueDataQualityRuleSetEvaluationRunOperator(
        task_id="glue_dq_silver",
        datasource={"GlueTable": {"DatabaseName": "stablecoin_payments_dev_lake", "TableName": "stablecoin_transfers"}},
        role=f"{PREFIX}-glue",
        rule_set_names=[f"{PREFIX}-silver-transfers"],
        show_results=True,
        verify_result_status=True,   # fail the DAG if any rule fails
    )

    crawl = GlueCrawlerOperator(task_id="crawl_lake", config={"Name": f"{PREFIX}-lake"})

    load_redshift = RedshiftDataOperator(
        task_id="load_redshift",
        workgroup_name=PREFIX,
        database="analytics",
        sql="CALL core.sp_load_from_lake();",
        wait_for_completion=True,
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command="cd /usr/local/airflow/dags/dbt && dbt build --target prod --profiles-dir . --fail-fast",
    )

    wait_for_source >> bronze >> silver >> glue_dq >> gold >> crawl >> load_redshift >> dbt_build
