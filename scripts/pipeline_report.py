"""Summarise a pipeline run: volumes per stage, timings, lake size per layer and DQ results.
Writes reports/pipeline_run.md (the 'scale' evidence quoted in the README)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LAKE = ROOT / "data" / "lake"


def batch_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    bronze, silver = {}, {}
    for log in sorted((ROOT / "logs").glob("*.log")):
        for line in log.read_text(errors="ignore").splitlines():
            if line.startswith('{"batch"'):
                m = json.loads(line)
                (bronze if "bronze_rows" in m else silver)[m["batch"]] = m   # last run wins
    return (pd.DataFrame(bronze.values()).sort_values("batch"),
            pd.DataFrame(silver.values()).sort_values("batch"))


def dir_size(p: Path) -> tuple[float, int]:
    total, files = 0, 0
    for dirpath, _, names in os.walk(p):
        for n in names:
            if n.endswith(".parquet"):
                total += os.path.getsize(os.path.join(dirpath, n))
                files += 1
    return total / 1e9, files


def main() -> None:
    b, s = batch_metrics()
    layers = []
    for layer in ["bronze/stablecoin_transfers", "bronze/blocks", "silver/contract_registry",
                  "silver/stablecoin_transfers", "gold/daily_kpis", "gold/hourly_activity", "gold/wallet_daily",
                  "gold/wallet_monthly", "gold/wallet_profile"]:
        gb, files = dir_size(LAKE / layer)
        n = duckdb.sql(f"select count(*) from read_parquet('{LAKE / layer}/**/*.parquet')").fetchall()[0][0] if files else 0
        layers.append({"table": layer, "rows": n, "size_gb": round(gb, 2), "parquet_files": files})
    layers = pd.DataFrame(layers)

    dq = duckdb.sql(f"""
        select dataset, count(*) as checks, sum(case when passed then 1 else 0 end) as passed,
               sum(case when not passed and severity = 'error' then 1 else 0 end) as failed_error,
               sum(case when not passed and severity = 'warn' then 1 else 0 end) as warned
        from read_parquet('{LAKE}/_dq_results/**/*.parquet', hive_partitioning = true, union_by_name = true)
        group by 1 order by 1
    """).df()

    scanned = int(b.all_token_transfers_scanned.sum())
    lines = [
        "# Pipeline run: scale and data quality",
        "",
        f"* Source rows scanned (all ERC-20 transfers, {b.batch.min()} to {b.batch.max()}): **{scanned:,}**",
        f"* Stablecoin + oracle rows landed in bronze: **{int(b.bronze_rows.sum()):,}**",
        f"* Blocks: **{int(b.blocks.sum()):,}**",
        f"* Bronze ingest time: {b.seconds.sum()/60:,.0f} min on a 4-core machine (local Spark 3.5, reading S3 directly)",
        f"* Silver build time: {s.seconds.sum()/60:,.0f} min" if len(s) else "",
        "",
        "## Lake tables",
        layers.to_markdown(index=False),
        "",
        "Bronze transfer partitions older than the last two months were deleted after silver was built, because the",
        "local machine has a small disk allowance. In AWS the same rule is an S3 lifecycle policy (bronze is",
        "replayable from the public source). Full bronze row counts are in the batch table below.",
        "",
        "## Data quality checks (all runs)",
        dq.to_markdown(index=False),
        "",
        "## Bronze batches",
        b[["batch", "days", "all_token_transfers_scanned", "bronze_rows", "blocks", "seconds"]].to_markdown(index=False),
    ]
    out = ROOT / "reports" / "pipeline_run.md"
    out.write_text("\n".join(re.sub(r"\s+$", "", x) for x in lines) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
