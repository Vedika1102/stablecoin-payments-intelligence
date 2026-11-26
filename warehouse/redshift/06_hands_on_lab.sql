-- =====================================================================================
-- 06  Hands-on lab: run this yourself in Redshift Query Editor v2, one block at a time.
--     Prerequisites: deploy (Redshift on), run-pipeline (Glue backfill), warehouse (dbt) workflows.
--     Replace <ACCOUNT_ID> below with your 12-digit AWS account id.
--     Screenshot what each block shows; the README links the screenshots.
-- =====================================================================================

-- Turn off the result cache so timings are real
SET enable_result_cache_for_session TO off;

-- -------------------------------------------------------------------------------------
-- Lab 1. Spectrum: what's in the lake, and partition pruning
-- -------------------------------------------------------------------------------------
SELECT schemaname, tablename, location
FROM svv_external_tables
WHERE schemaname IN ('lake', 'public_eth')
ORDER BY 1, 2;

-- One day of transfers, read straight from S3. Only one block_date partition is scanned.
SELECT token_symbol, COUNT(*) AS transfers, ROUND(SUM(amount_usd) / 1e9, 2) AS volume_usd_bn
FROM lake.stablecoin_transfers
WHERE block_date = '2024-03-13'
GROUP BY 1
ORDER BY 2 DESC;

-- How much did that scan cost? (Spectrum bills per TB scanned)
SELECT query, ROUND(s3_scanned_bytes / 1e6, 1) AS mb_scanned, s3_scanned_rows, files
FROM svl_s3query_summary
ORDER BY starttime DESC
LIMIT 5;

-- -------------------------------------------------------------------------------------
-- Lab 2. COPY: load the largest fact (wallet x day, ~86M rows) month by month
-- -------------------------------------------------------------------------------------
-- Creates core.fct_wallet_daily (DISTKEY wallet, SORTKEY activity_date) and the other DDL.
-- Run the whole of 02_core_tables.sql and 03_load_procedure.sql first, then:

CREATE OR REPLACE PROCEDURE core.sp_backfill(lake_root VARCHAR(256), first_month DATE, last_month DATE)
AS $$
DECLARE
    m DATE := first_month;
BEGIN
    WHILE m <= last_month LOOP
        CALL core.sp_load_from_lake(lake_root, TO_CHAR(m, 'YYYY-MM'));
        m := DATEADD(month, 1, m);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

CALL core.sp_backfill('s3://stablecoin-payments-dev-lake-<ACCOUNT_ID>', '2023-07-01', '2025-06-01');

SELECT * FROM staging.load_audit ORDER BY load_month;

-- Reconcile: Redshift table vs the Parquet in S3 (should be identical)
SELECT 'redshift' AS source, COUNT(*) AS rows, SUM(sent_n) AS sent FROM core.fct_wallet_daily
UNION ALL
SELECT 'spectrum', COUNT(*), SUM(sent_n) FROM lake.wallet_daily;

-- Did any COPY reject rows?
SELECT * FROM sys_load_error_detail ORDER BY start_time DESC LIMIT 10;

-- -------------------------------------------------------------------------------------
-- Lab 3. Distribution keys: co-located vs redistributed joins
-- -------------------------------------------------------------------------------------
-- Same DISTKEY(wallet) on both sides: expect DS_DIST_NONE in the plan (no data movement).
EXPLAIN
SELECT d.segment, COUNT(*) AS wallet_days, SUM(f.sent_usd) AS sent_usd
FROM core.fct_wallet_daily f
JOIN core.dim_wallet d
  ON d.wallet = f.wallet
 AND f.activity_date BETWEEN d.valid_from AND d.valid_to
GROUP BY 1;

-- Join on a non-distribution column: expect DS_BCAST_INNER or DS_DIST_BOTH (data moved between slices).
EXPLAIN
SELECT f.activity_date, COUNT(*)
FROM core.fct_wallet_daily f
JOIN core.fct_wallet_monthly m ON m.activity_month = DATE_TRUNC('month', f.activity_date)
GROUP BY 1;

-- Run the co-located query for real and note the time
SELECT d.segment, COUNT(*) AS wallet_days, ROUND(SUM(f.sent_usd) / 1e9, 1) AS sent_usd_bn
FROM core.fct_wallet_daily f
JOIN core.dim_wallet d
  ON d.wallet = f.wallet
 AND f.activity_date BETWEEN d.valid_from AND d.valid_to
GROUP BY 1
ORDER BY 3 DESC;

-- -------------------------------------------------------------------------------------
-- Lab 4. Sort keys and zone maps: the same filter on a sorted vs unsorted column
-- -------------------------------------------------------------------------------------
SELECT COUNT(*) FROM core.fct_wallet_daily WHERE activity_date BETWEEN '2024-03-01' AND '2024-03-31';
SELECT COUNT(*) FROM core.fct_wallet_daily WHERE max_sent_usd BETWEEN 1000 AND 2000;

-- Compare blocks read: the sorted filter skips most blocks
SELECT query_id, LEFT(query_text, 80) AS sql, elapsed_time / 1000 AS ms
FROM sys_query_history
WHERE query_text ILIKE 'SELECT COUNT(*) FROM core.fct_wallet_daily WHERE%'
ORDER BY start_time DESC
LIMIT 2;

-- -------------------------------------------------------------------------------------
-- Lab 5. Table health and skew
-- -------------------------------------------------------------------------------------
SELECT "schema", "table", diststyle, sortkey1, tbl_rows, size AS size_mb, skew_rows, unsorted, stats_off
FROM svv_table_info
WHERE "schema" IN ('core', 'marts')
ORDER BY tbl_rows DESC;

-- -------------------------------------------------------------------------------------
-- Lab 6. Business questions in SQL: run 04_analytical_queries.sql (window functions,
--        QUALIFY, NTILE, SCD2 history, Spectrum + local join, materialized view)
-- -------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------
-- Lab 7. Monitoring: run 05_performance_and_monitoring.sql, then check what the lab cost
-- -------------------------------------------------------------------------------------
SELECT DATE_TRUNC('hour', start_time) AS hour, ROUND(SUM(charged_seconds) / 3600.0, 2) AS rpu_hours
FROM sys_serverless_usage
GROUP BY 1
ORDER BY 1 DESC;
