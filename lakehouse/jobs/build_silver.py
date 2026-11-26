"""
Silver: cleaned, conformed, enriched stablecoin transfers (one row per transfer event).

  * canonical 20-byte addresses, token symbol/decimals, human amounts
  * dedup on (transaction_hash, log_index), keeping the latest re-published version
  * transfer_kind (mint / burn / transfer) and flow_type (EOA vs contract on each side)
  * network fee context from the block: base fee (gwei) and estimated USD cost of an ERC-20
    transfer, using an hourly ETH/USD price derived on-chain from the USDC/WETH Uniswap pool
  * ticket-size bucket

Also writes silver/eth_usd_hourly (the derived price series) and silver/blocks.

    python -m lakehouse.jobs.build_silver --start 2023-07-01 --end 2025-06-30
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time

from pyspark.sql import functions as F

from lakehouse.config import ERC20_TRANSFER_GAS, UNISWAP_USDC_WETH_POOL, WETH, ZERO_ADDRESS, Paths, load_tokens
from lakehouse.dq import DQRunner
from lakehouse.jobs.ingest_bronze import month_batches
from lakehouse.spark_session import get_spark
from lakehouse.transforms import dedupe_latest, normalize_address, scale_amount, ticket_bucket, transfer_kind

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def eth_price_hourly(rows):
    """ETH/USD per hour from pool swaps: in one swap tx the pool sends one token and receives the
    other. price = USDC amount / WETH amount, median per hour, ignoring dust trades."""
    legs = (rows.where(F.col("token_address").isin(USDC, WETH))
            .where((F.col("from_n") == UNISWAP_USDC_WETH_POOL) | (F.col("to_n") == UNISWAP_USDC_WETH_POOL))
            .groupBy("transaction_hash", "hour_ts")
            .agg(F.sum(F.when(F.col("token_address") == USDC, F.col("amount"))).alias("usdc"),
                 F.sum(F.when(F.col("token_address") == WETH, F.col("amount"))).alias("weth"))
            .where("usdc >= 50 and weth >= 0.02"))
    return (legs.withColumn("px", F.col("usdc") / F.col("weth"))
            .groupBy("hour_ts")
            .agg(F.percentile_approx("px", 0.5, 1000).alias("eth_usd"), F.count("*").alias("swaps")))


def run_batch(spark, paths: Paths, days, tokens_df, registry) -> dict:
    t0 = time.time()
    label = days[0].strftime("%Y-%m")
    dates = [d.isoformat() for d in days]
    br = spark.read.parquet(f"{paths.bronze}/stablecoin_transfers").where(F.col("date").isin(dates))
    blocks = (spark.read.parquet(f"{paths.bronze}/blocks").where(F.col("date").isin(dates))
              .select(F.col("number").alias("block_number"),
                      (F.col("base_fee_per_gas") / 1e9).alias("base_fee_gwei"),
                      (F.col("gas_used") / F.col("gas_limit")).alias("block_utilization"),
                      F.col("transaction_count").alias("block_tx_count")))

    rows = (dedupe_latest(br, ["transaction_hash", "log_index"], "last_modified")
            .withColumn("from_n", normalize_address(F.col("from_address")))
            .withColumn("to_n", normalize_address(F.col("to_address")))
            .withColumn("hour_ts", F.date_trunc("hour", "block_timestamp"))
            .join(F.broadcast(tokens_df), "token_address", "left")
            .withColumn("amount", F.when(F.col("token_address") == WETH, F.col("value") / 1e18)
                        .otherwise(scale_amount(F.col("value"), F.col("decimals"))))
            .cache())

    px = eth_price_hourly(rows).cache()
    px.write.mode("overwrite").parquet(f"{paths.silver}/eth_usd_hourly/month={label}")

    stable = rows.where(F.col("symbol").isNotNull())
    # The registry has ~80M addresses; a month touches a few million. Semi-join once to get the
    # month's contracts (small), then broadcast it to both sides. Avoids two 80M-row shuffles.
    month_addrs = (stable.select(F.col("from_n").alias("addr"))
                   .union(stable.select(F.col("to_n").alias("addr"))).distinct())
    contracts = (month_addrs.join(registry.select(F.col("address").alias("addr")), "addr", "left_semi")
                 .cache())
    contracts.count()
    s = (stable
         .join(F.broadcast(blocks), "block_number", "left")
         .join(F.broadcast(px.select("hour_ts", "eth_usd")), "hour_ts", "left")
         .join(F.broadcast(contracts.withColumnRenamed("addr", "from_n").withColumn("from_is_contract", F.lit(True))),
               "from_n", "left")
         .join(F.broadcast(contracts.withColumnRenamed("addr", "to_n").withColumn("to_is_contract", F.lit(True))),
               "to_n", "left")
         .withColumn("from_is_contract", F.coalesce("from_is_contract", F.lit(False)))
         .withColumn("to_is_contract", F.coalesce("to_is_contract", F.lit(False)))
         .withColumn("amount_usd", F.col("amount"))  # all four tokens are USD-pegged; depeg risk noted in docs
         .withColumn("est_fee_usd", F.col("base_fee_gwei") * 1e-9 * ERC20_TRANSFER_GAS * F.col("eth_usd"))
         .withColumn("fee_to_amount_bps", F.when(F.col("amount_usd") > 0,
                                                 F.col("est_fee_usd") / F.col("amount_usd") * 1e4))
         .withColumn("transfer_kind", transfer_kind(F.col("from_n"), F.col("to_n"), ZERO_ADDRESS))
         .withColumn("flow_type", F.concat(F.when(F.col("from_is_contract"), "contract").otherwise("eoa"),
                                           F.lit("_to_"),
                                           F.when(F.col("to_is_contract"), "contract").otherwise("eoa")))
         .withColumn("ticket_bucket", ticket_bucket(F.col("amount_usd")))
         .select(F.col("date").alias("block_date"), "block_timestamp", "hour_ts", "block_number",
                 "transaction_hash", "log_index", "token_address", F.col("symbol").alias("token_symbol"),
                 F.col("from_n").alias("from_address"), F.col("to_n").alias("to_address"),
                 "amount", "amount_usd", "ticket_bucket", "transfer_kind", "flow_type",
                 "from_is_contract", "to_is_contract", "base_fee_gwei", "block_utilization",
                 "eth_usd", "est_fee_usd", "fee_to_amount_bps")
         .cache())

    dq = DQRunner(spark, "silver_stablecoin_transfers", label)
    n = dq.row_count_min(s, 100_000)
    dq.unique(s, ["transaction_hash", "log_index"])
    dq.not_null(s, ["token_symbol", "from_address", "to_address", "amount_usd", "base_fee_gwei"])
    dq.regex_match_rate(s, "from_address", r"^0x[0-9a-f]{40}$")
    dq.in_range(s, "amount_usd", lo=0)
    price_cov = s.select(F.avg(F.col("eth_usd").isNotNull().cast("double"))).first()[0]
    dq.custom("eth_price_coverage", price_cov >= 0.99, price_cov, ">= 0.99")
    pr = px.agg(F.min("eth_usd").alias("lo"), F.max("eth_usd").alias("hi")).first()
    dq.custom("eth_price_plausible", 500 <= pr["lo"] and pr["hi"] <= 10_000, pr["hi"], "500..10000 USD", "warn")
    dq.publish(paths.dq)

    s.repartition("block_date").write.mode("overwrite").partitionBy("block_date").parquet(
        f"{paths.silver}/stablecoin_transfers")
    rows.unpersist(); px.unpersist(); s.unpersist(); contracts.unpersist()
    m = {"batch": label, "silver_rows": int(n), "seconds": round(time.time() - t0, 1)}
    print(json.dumps(m))
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    yesterday = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    ap.add_argument("--start", default=yesterday, help="default: yesterday UTC (daily scheduled run)")
    ap.add_argument("--end", default=yesterday)
    args, _ = ap.parse_known_args()  # Glue appends its own --JOB_NAME etc.
    paths = Paths()
    spark = get_spark("build_silver")
    tokens_df = spark.createDataFrame(load_tokens()).select(
        "token_address", "symbol", F.col("decimals").cast("int").alias("decimals"))
    registry = spark.read.parquet(f"{paths.silver}/contract_registry")
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    metrics = [run_batch(spark, paths, days, tokens_df, registry) for days in month_batches(start, end)]
    (spark.createDataFrame(metrics).withColumn("run_ts", F.current_timestamp())
     .write.mode("append").parquet(f"{paths.lake}/_job_metrics/build_silver"))
    spark.stop()


if __name__ == "__main__":
    main()
