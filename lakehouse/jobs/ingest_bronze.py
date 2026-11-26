"""
Bronze ingest: stablecoin transfers + blocks from the AWS Public Blockchain dataset.

Reads the public Parquet in place (s3a:// locally, s3:// on Glue/EMR), keeps the four USD
stablecoins plus the WETH legs of the USDC/WETH Uniswap pool (our on-chain ETH price oracle),
and lands them unchanged (raw padded addresses, raw integer amounts) with ingest metadata.
Processes one month per batch; each batch is idempotent (dynamic partition overwrite).

    python -m lakehouse.jobs.ingest_bronze --start 2023-07-01 --end 2025-06-30
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time

from pyspark.sql import functions as F

from lakehouse.config import UNISWAP_USDC_WETH_POOL, WETH, Paths, load_tokens
from lakehouse.dq import DQRunner
from lakehouse.spark_session import get_spark
from lakehouse.transforms import address_padding_is_clean, normalize_address


def month_batches(start: dt.date, end: dt.date):
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        days = [cur + dt.timedelta(days=i) for i in range((nxt - cur).days)]
        yield [d for d in days if start <= d <= end]
        cur = nxt


class SourceNotReady(RuntimeError):
    """The public dataset has not published a requested day yet (the scheduler retries)."""


def assert_source_ready(spark, paths: Paths, dates: list[str]) -> None:
    jvm = spark._jvm
    conf = spark._jsc.hadoopConfiguration()
    for d in (dates[0], dates[-1]):
        p = jvm.org.apache.hadoop.fs.Path(f"{paths.source}/token_transfers/date={d}")
        if not p.getFileSystem(conf).exists(p):
            raise SourceNotReady(f"source partition date={d} not published yet")


def run_batch(spark, paths: Paths, days: list[dt.date], stable: list[str]) -> dict:
    t0 = time.time()
    label = days[0].strftime("%Y-%m")
    dates = [d.isoformat() for d in days]
    assert_source_ready(spark, paths, dates)

    def src(table):
        base = f"{paths.source}/{table}"
        return (spark.read.option("basePath", base)
                .parquet(*[f"{base}/date={d}" for d in dates]))

    tt = src("token_transfers")
    pool = UNISWAP_USDC_WETH_POOL
    keep = (F.col("token_address").isin(stable)
            | ((F.col("token_address") == WETH)
               & ((normalize_address(F.col("from_address")) == pool) | (normalize_address(F.col("to_address")) == pool))))

    # One pass over the month: daily totals for *all* token transfers (context for market share)
    # and the filtered stablecoin rows. cache() keeps the filtered set for DQ + write.
    daily_all = tt.groupBy("date").agg(F.count("*").alias("all_token_transfers"))
    bronze = (tt.where(keep)
              .withColumn("_ingested_at", F.current_timestamp())
              .withColumn("_source_file", F.input_file_name())
              .cache())

    blocks = (src("blocks")
              .select("number", "hash", "timestamp", "base_fee_per_gas", "gas_used", "gas_limit",
                      "transaction_count", "date", "last_modified")
              .withColumn("_ingested_at", F.current_timestamp())
              .cache())

    dq = DQRunner(spark, "bronze_stablecoin_transfers", label)
    n = dq.row_count_min(bronze, 100_000)
    dq.not_null(bronze, ["token_address", "from_address", "to_address", "transaction_hash",
                         "log_index", "block_number", "block_timestamp"])
    dq.regex_match_rate(bronze, "transaction_hash", r"^0x[0-9a-f]{64}$")
    clean = bronze.select(F.avg((address_padding_is_clean(F.col("from_address"))
                                 & address_padding_is_clean(F.col("to_address"))).cast("double"))).first()[0]
    dq.custom("address_padding_clean_rate", clean >= 0.9999, clean, ">= 0.9999")
    dq.referential(bronze, blocks, "block_number", "number")
    dq.publish(paths.dq)

    dqb = DQRunner(spark, "bronze_blocks", label)
    nb = dqb.row_count_min(blocks, 6_000 * len(days))
    dqb.contiguous_sequence(blocks, "number")
    dqb.unique(blocks, ["number"])
    dqb.not_null(blocks, ["number", "timestamp", "base_fee_per_gas"])
    dqb.publish(paths.dq)

    (bronze.repartition("date").write.mode("overwrite").partitionBy("date")
     .parquet(f"{paths.bronze}/stablecoin_transfers"))
    (blocks.repartition("date").write.mode("overwrite").partitionBy("date")
     .parquet(f"{paths.bronze}/blocks"))

    stats = (daily_all.join(bronze.groupBy("date").agg(
                F.sum(F.col("token_address").isin(stable).cast("int")).alias("stablecoin_transfers")), "date", "left")
             .withColumn("_ingested_at", F.current_timestamp()))
    stats.coalesce(1).write.mode("overwrite").partitionBy("date").parquet(f"{paths.bronze}/source_daily_stats")
    all_n = stats.agg(F.sum("all_token_transfers")).first()[0]

    bronze.unpersist()
    blocks.unpersist()
    m = {"batch": label, "days": len(days), "all_token_transfers_scanned": int(all_n),
         "bronze_rows": int(n), "blocks": int(nb), "seconds": round(time.time() - t0, 1)}
    print(json.dumps(m))
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    yesterday = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    ap.add_argument("--start", default=yesterday, help="default: yesterday UTC (daily scheduled run)")
    ap.add_argument("--end", default=yesterday)
    args, _ = ap.parse_known_args()  # Glue appends its own --JOB_NAME etc.
    paths = Paths()
    spark = get_spark("ingest_bronze")
    stable = [t["token_address"] for t in load_tokens()]
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    metrics = [run_batch(spark, paths, days, stable) for days in month_batches(start, end)]
    (spark.createDataFrame(metrics).withColumn("run_ts", F.current_timestamp())
     .write.mode("append").parquet(f"{paths.lake}/_job_metrics/ingest_bronze"))
    spark.stop()


if __name__ == "__main__":
    main()
