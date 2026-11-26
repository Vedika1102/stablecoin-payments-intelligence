"""
Gold: analysis-ready aggregates for the warehouse, the stats work and the dashboard.

  daily_kpis       date x token x ticket bucket x transfer kind x flow type
  hourly_activity  hour x token x ticket bucket (EOA-to-EOA transfers) with fee context: the panel
                   for fee-elasticity and the Dencun diff-in-diff
  hourly_network   hour: base fee, block utilization, ETH/USD
  wallet_daily     EOA wallet x day activity (the biggest table; feeds lifecycle metrics)
  wallet_monthly   EOA wallet x month activity + behavioural segment (feeds SCD2 dim_wallet)
  wallet_profile   one row per EOA wallet: first seen / first receive / first send, lifetime totals

    python -m lakehouse.jobs.build_gold
"""

from __future__ import annotations

import time

from pyspark.sql import functions as F

from lakehouse.config import Paths
from lakehouse.dq import DQRunner
from lakehouse.spark_session import get_spark


def segment_expr() -> F.Column:
    """Monthly behavioural segment, first matching rule wins. Thresholds are documented in
    docs/metric_definitions.md and tested for sensitivity in the analysis."""
    cps = F.col("counterparties_out") + F.col("counterparties_in")
    return (F.when((cps >= 100) | ((F.col("sent_n") + F.col("recv_n")) >= 500), "high_throughput_service")
            .when(F.col("sent_n") == 0, "receive_only")
            .when(F.col("to_contract_share") >= 0.5, "defi_contract_user")
            .when(F.col("avg_ticket_sent") >= 100_000, "large_value_mover")
            .when((F.col("avg_ticket_sent") < 10_000) & (F.col("counterparties_out") <= 20), "payment_like")
            .otherwise("other"))


def main() -> None:
    t0 = time.time()
    paths = Paths()
    spark = get_spark("build_gold")
    s = spark.read.parquet(f"{paths.silver}/stablecoin_transfers")

    # ---- 1. daily KPIs ------------------------------------------------------------------------
    daily = (s.groupBy("block_date", "token_symbol", "ticket_bucket", "transfer_kind", "flow_type")
             .agg(F.count("*").alias("transfers"), F.sum("amount_usd").alias("volume_usd"),
                  F.approx_count_distinct("from_address").alias("senders_approx"),
                  F.approx_count_distinct("to_address").alias("receivers_approx"),
                  F.avg("base_fee_gwei").alias("avg_base_fee_gwei"),
                  F.percentile_approx("est_fee_usd", 0.5).alias("median_fee_usd"),
                  F.percentile_approx("amount_usd", 0.5).alias("median_amount_usd")))
    daily.coalesce(4).write.mode("overwrite").parquet(f"{paths.gold}/daily_kpis")

    # ---- 2. hourly panel ----------------------------------------------------------------------
    hourly = (s.where("transfer_kind = 'transfer' and flow_type = 'eoa_to_eoa'")
              .groupBy("hour_ts", "token_symbol", "ticket_bucket")
              .agg(F.count("*").alias("transfers"), F.sum("amount_usd").alias("volume_usd"),
                   F.avg("base_fee_gwei").alias("avg_base_fee_gwei"),
                   F.avg("est_fee_usd").alias("avg_fee_usd")))
    hourly.coalesce(4).write.mode("overwrite").parquet(f"{paths.gold}/hourly_activity")

    blocks = spark.read.parquet(f"{paths.bronze}/blocks")
    px = spark.read.parquet(f"{paths.silver}/eth_usd_hourly")
    network = (blocks.withColumn("hour_ts", F.date_trunc("hour", "timestamp"))
               .groupBy("hour_ts")
               .agg(F.avg(F.col("base_fee_per_gas") / 1e9).alias("avg_base_fee_gwei"),
                    F.avg(F.col("gas_used") / F.col("gas_limit")).alias("avg_block_utilization"),
                    F.sum("transaction_count").alias("network_tx_count"),
                    F.count("*").alias("blocks"))
               .join(px.select("hour_ts", "eth_usd", "swaps"), "hour_ts", "left"))
    network.coalesce(1).write.mode("overwrite").parquet(f"{paths.gold}/hourly_network")

    # ---- 3. wallet x day (EOAs only, real transfers only) -------------------------------------
    # Wallet tables exclude sub-cent "address poisoning" spam: the look-alike addresses it creates
    # would otherwise flood the new-wallet cohorts with fake wallets.
    t = s.where("transfer_kind = 'transfer' and amount_usd >= 0.01")
    def wallet_day(tm):
        out_side = (tm.where(~F.col("from_is_contract"))
                    .select(F.col("from_address").alias("wallet"), "block_date", "block_timestamp", "token_symbol",
                            "amount_usd", F.col("to_address").alias("counterparty"),
                            F.col("to_is_contract").alias("cp_is_contract"), F.lit("out").alias("direction")))
        in_side = (tm.where(~F.col("to_is_contract"))
                   .select(F.col("to_address").alias("wallet"), "block_date", "block_timestamp", "token_symbol",
                           "amount_usd", F.col("from_address").alias("counterparty"),
                           F.col("from_is_contract").alias("cp_is_contract"), F.lit("in").alias("direction")))
        legs = out_side.unionByName(in_side)
        is_out, is_in = F.col("direction") == "out", F.col("direction") == "in"
        return (legs.groupBy("wallet", "block_date")
                .agg(F.sum(is_out.cast("int")).alias("sent_n"),
                     F.sum(F.when(is_out, F.col("amount_usd")).otherwise(0)).alias("sent_usd"),
                     F.sum(is_in.cast("int")).alias("recv_n"),
                     F.sum(F.when(is_in, F.col("amount_usd")).otherwise(0)).alias("recv_usd"),
                     F.sum((is_out & (F.col("amount_usd") < 1000)).cast("int")).alias("sent_small_n"),
                     F.sum((is_out & F.col("cp_is_contract")).cast("int")).alias("sent_to_contract_n"),
                     F.approx_count_distinct(F.when(is_out, F.col("counterparty"))).alias("counterparties_out"),
                     F.approx_count_distinct(F.when(is_in, F.col("counterparty"))).alias("counterparties_in"),
                     F.sum((F.col("token_symbol") == "USDC").cast("int")).alias("usdc_n"),
                     F.sum((F.col("token_symbol") == "USDT").cast("int")).alias("usdt_n"),
                     F.sum((F.col("token_symbol") == "DAI").cast("int")).alias("dai_n"),
                     F.sum((F.col("token_symbol") == "PYUSD").cast("int")).alias("pyusd_n"),
                     F.max(F.when(is_out, F.col("amount_usd"))).alias("max_sent_usd"),
                     # earliest receipt of the day; min() over a struct ignores nulls and orders by timestamp first
                     F.min(F.when(is_in, F.struct("block_timestamp", "amount_usd", "token_symbol"))).alias("first_recv"))
                .withColumn("block_month", F.date_format("block_date", "yyyy-MM")))

    # Built one month at a time: each month's shuffle is ~1/24 of the window, so spill stays small and
    # any month can be rebuilt on its own (dynamic partition overwrite).
    months = sorted({r[0] for r in t.select(F.date_format("block_date", "yyyy-MM")).distinct().collect()})
    for m in months:
        tm = t.where(F.date_format("block_date", "yyyy-MM") == m)
        (wallet_day(tm).repartition(4).write.mode("overwrite").partitionBy("block_month")
         .parquet(f"{paths.gold}/wallet_daily"))
        spark.sparkContext._jvm.System.gc()   # lets Spark's ContextCleaner drop finished shuffle files
    wd = spark.read.parquet(f"{paths.gold}/wallet_daily")

    # ---- 4. wallet x month + segment ---------------------------------------------------------
    wm = (wd.groupBy("wallet", "block_month")
          .agg(F.count("*").alias("active_days"), F.sum("sent_n").alias("sent_n"), F.sum("sent_usd").alias("sent_usd"),
               F.sum("recv_n").alias("recv_n"), F.sum("recv_usd").alias("recv_usd"),
               F.sum("sent_small_n").alias("sent_small_n"), F.sum("sent_to_contract_n").alias("sent_to_contract_n"),
               F.sum("counterparties_out").alias("counterparties_out"),   # upper bound across days
               F.sum("counterparties_in").alias("counterparties_in"),
               F.sum("usdc_n").alias("usdc_n"), F.sum("usdt_n").alias("usdt_n"))
          .withColumn("to_contract_share", F.when(F.col("sent_n") > 0, F.col("sent_to_contract_n") / F.col("sent_n")))
          .withColumn("avg_ticket_sent", F.when(F.col("sent_n") > 0, F.col("sent_usd") / F.col("sent_n")))
          .withColumn("segment", segment_expr()))
    wm.repartition(8).write.mode("overwrite").parquet(f"{paths.gold}/wallet_monthly")

    # ---- 5. wallet profile (lifecycle milestones) --------------------------------------------
    prof = (wd.groupBy("wallet")
            .agg(F.min("block_date").alias("first_seen_date"),
                 F.min(F.when(F.col("recv_n") > 0, F.col("block_date"))).alias("first_receive_date"),
                 F.min(F.when(F.col("sent_n") > 0, F.col("block_date"))).alias("first_send_date"),
                 F.max("block_date").alias("last_active_date"),
                 F.count("*").alias("active_days"),
                 F.sum("sent_n").alias("lifetime_sent_n"), F.sum("sent_usd").alias("lifetime_sent_usd"),
                 F.sum("recv_n").alias("lifetime_recv_n"), F.sum("recv_usd").alias("lifetime_recv_usd"),
                 F.sum("usdc_n").alias("usdc_n"), F.sum("usdt_n").alias("usdt_n"),
                 F.min("first_recv").alias("f"))
            .withColumn("first_receive_usd", F.col("f.amount_usd"))
            .withColumn("first_receive_token", F.col("f.token_symbol"))
            .drop("f")
            .withColumn("primary_token", F.when(F.col("usdc_n") >= F.col("usdt_n"), "USDC").otherwise("USDT")))
    prof.repartition(8).write.mode("overwrite").parquet(f"{paths.gold}/wallet_profile")

    # ---- DQ: gold reconciles to silver --------------------------------------------------------
    g_daily = spark.read.parquet(f"{paths.gold}/daily_kpis")
    dq = DQRunner(spark, "gold", "full")
    s_n, s_v = s.agg(F.count("*"), F.sum("amount_usd")).first()
    g_n, g_v = g_daily.agg(F.sum("transfers"), F.sum("volume_usd")).first()
    dq.custom("daily_kpis_rowcount_reconciles", s_n == g_n, g_n - s_n, "== silver rows")
    dq.custom("daily_kpis_volume_reconciles", abs(g_v - s_v) <= 1e-6 * s_v, g_v - s_v, "|diff| <= 1e-6 rel")
    wd_out = spark.read.parquet(f"{paths.gold}/wallet_daily").agg(F.sum("sent_n")).first()[0]
    eoa_out = t.where(~F.col("from_is_contract")).count()
    dq.custom("wallet_daily_sent_reconciles", wd_out == eoa_out, wd_out - eoa_out, "== EOA-sent transfers")
    dq.unique(spark.read.parquet(f"{paths.gold}/wallet_profile"), ["wallet"])
    dq.publish(paths.dq)
    print(f"gold done in {time.time() - t0:,.0f}s")
    spark.stop()


if __name__ == "__main__":
    main()
