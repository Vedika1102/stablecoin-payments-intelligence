# Architecture

```mermaid
flowchart LR
    subgraph SRC["Source: AWS Public Blockchain Data (s3://aws-public-blockchain, us-east-2)"]
        TT["eth/token_transfers<br/>Parquet, date= partitions<br/>~35-90M rows/month"]
        BL["eth/blocks"]
        CT["eth/contracts"]
    end

    subgraph GLUE["AWS Glue 5.0 / EMR Serverless (PySpark 3.5)"]
        B["ingest_bronze<br/>filter 4 stablecoins + oracle legs<br/>DQ: completeness, FK to blocks"]
        R["build_contract_registry<br/>~80M+ contract addresses"]
        S["build_silver<br/>dedup, address normalization, decimals,<br/>on-chain ETH/USD, fees, flow type"]
        G["build_gold<br/>daily/hourly KPIs, wallet x day,<br/>wallet x month + segment, wallet profile"]
    end

    subgraph LAKE["S3 data lake (Parquet, zstd, partitioned)"]
        BZ[("bronze/")]
        SV[("silver/")]
        GD[("gold/")]
        DQ[("_dq_results/")]
    end

    CAT["Glue Data Catalog<br/>+ partition projection<br/>+ Glue Data Quality (DQDL)"]
    ATH["Athena<br/>(ad hoc, cost-capped workgroup)"]

    subgraph RS["Redshift Serverless"]
        SP["Spectrum external schemas<br/>lake / public_eth"]
        CORE["core: dim_wallet (SCD2), dim_token,<br/>dim_date, fct_wallet_monthly,<br/>fct_transfers_daily, fct_network_hourly"]
        MARTS["marts: payment mix, fee panel,<br/>activation funnel, cohorts, DQ scorecard"]
    end

    DBT["dbt (tests + docs)<br/>prod: Redshift, dev/CI: DuckDB"]
    BI["Tableau Public dashboard"]
    PY["Python stats<br/>regression, DiD, chi-squared,<br/>survival, logistic"]

    TT --> B
    BL --> B
    CT --> R
    B --> BZ --> S
    R --> S
    S --> SV --> G --> GD
    B & S & G --> DQ
    LAKE --> CAT --> ATH
    CAT --> SP --> CORE
    GD -->|COPY| CORE
    DBT --> CORE --> MARTS
    MARTS --> BI
    MARTS --> PY

    SF["Step Functions (daily, EventBridge 03:00 UTC)<br/>or Airflow / MWAA DAG"] -.orchestrates.-> B & S & G & CORE
    TF["Terraform: S3, IAM, Glue, Athena,<br/>Redshift Serverless, Step Functions,<br/>SNS + CloudWatch alarms"] -.provisions.-> GLUE & LAKE & RS & SF
    CI["GitHub Actions: lint, unit tests,<br/>terraform validate, real-data smoke run,<br/>OIDC deploy"] -.ships.-> TF
```

## Design decisions

| Decision | Why | Trade-off |
|---|---|---|
| Read the public bucket in place (s3a locally, s3 on Glue) instead of copying it | No 10+ TB copy. Column pruning and partition pruning mean a month costs ~4 GB of reads, not the full files. | Depends on the public dataset's schema staying stable; bronze DQ checks catch drift. |
| Bronze keeps raw padded addresses and raw integer amounts | Bronze must be replayable and auditable against the source. Normalization lives in silver, where it's unit-tested. | Bronze is slightly larger. |
| ETH/USD derived from Uniswap swaps, not an API | Fully reproducible from the same dataset, with no external dependency or licence. | Hourly median, ignores dust; validated by a plausibility DQ check. |
| Transfer-level detail stays in S3 (Spectrum); aggregates go to Redshift | ~300M rows for two years, billions for full history. Dashboards only need aggregates. Spectrum handles the occasional drill-down. | Drill-downs are slower and bill per TB scanned. The analyst Athena workgroup has a 200 GB per-query cap. |
| `DISTKEY(wallet)` on dim_wallet and the wallet facts | SCD2 as-of joins and cohort building are wallet-keyed, so they co-locate with no redistribution. | Whale wallets can skew slices; monitored with `svv_table_info.skew_rows`. |
| SCD2 on wallet segment (gaps-and-islands) | Segments change month to month. Reports must show the segment a wallet had *at the time*. | More rows than a Type 1 dimension. |
| Dynamic partition overwrite everywhere | Any day or month can be re-run idempotently, so backfills are safe. | One writer per table (Glue `max_concurrent_runs = 1`). |
| Contract flags via semi-join + broadcast | The registry has 78.6M addresses; a month touches a few million. Semi-joining once gives a small contract set that is broadcast to both sides of the transfer. | One extra pass over the month's distinct addresses. |
| Gold wallet tables built month by month | Each month's shuffle is about 1/24 of the window, so spill stays small and any month can be rebuilt alone. Monthly and lifetime tables then read the compact wallet x day table. | A loop of 24 small jobs instead of one big one. |
| dbt with DuckDB for dev/CI and Redshift for prod | Same SQL tested on every PR against real data, without a cluster. | Dialect differences handled with dbt cross-database macros. |

## Scale and cost (two-year window, measured locally)

Measured numbers are in `reports/pipeline_run.md` after a run. Rough AWS cost to run the full
two-year backfill once: Glue at 10 G.1X workers x ~2 h x $0.44/DPU-h ≈ $9. Athena exploration is
$5/TB scanned, and typical queries scan under 5 GB. Redshift Serverless at 8 RPU is $0.375/RPU-h,
billed only while queries run.
