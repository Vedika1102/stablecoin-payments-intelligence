"""
Contract registry: every contract address created on Ethereum up to --end, from the public
`contracts` table. Used to label each side of a transfer as a contract (DEX pool, exchange
deposit contract, smart wallet, bridge...) or an externally owned account (a person or a bot key).

Reads only two columns across ~3,600 daily partitions; Parquet column pruning keeps the
transfer small.

    python -m lakehouse.jobs.build_contract_registry --end 2025-06-30
"""

from __future__ import annotations

import argparse
import datetime as dt

from pyspark.sql import functions as F

from lakehouse.config import Paths
from lakehouse.dq import DQRunner
from lakehouse.spark_session import get_spark

FIRST_DAY = dt.date(2015, 7, 30)


def main() -> None:
    ap = argparse.ArgumentParser()
    yesterday = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    ap.add_argument("--end", default=yesterday, help="default: yesterday UTC (daily scheduled run)")
    ap.add_argument("--since", default=FIRST_DAY.isoformat(),
                    help="CI smoke runs use a recent start date; production uses full history")
    ap.add_argument("--min-rows", type=int, default=1_000_000)
    args, _ = ap.parse_known_args()  # Glue appends its own --JOB_NAME etc.
    end = dt.date.fromisoformat(args.end)
    paths = Paths()
    spark = get_spark("build_contract_registry")
    base = f"{paths.source}/contracts"
    # Let Spark discover the partitions that exist, then prune to <= end
    df = (spark.read.parquet(base)
          .where((F.col("date") >= args.since) & (F.col("date") <= end.isoformat()))
          .select(F.lower("address").alias("address"), F.col("block_timestamp").alias("created_at"))
          .groupBy("address").agg(F.min("created_at").alias("created_at")))
    df = df.cache()
    dq = DQRunner(spark, "silver_contract_registry", end.isoformat())
    dq.row_count_min(df, args.min_rows)
    dq.regex_match_rate(df, "address", r"^0x[0-9a-f]{40}$")
    dq.publish(paths.dq)
    df.repartition(16, "address").write.mode("overwrite").parquet(f"{paths.silver}/contract_registry")
    print(f"contract registry rows: {df.count():,}")
    spark.stop()


if __name__ == "__main__":
    main()
