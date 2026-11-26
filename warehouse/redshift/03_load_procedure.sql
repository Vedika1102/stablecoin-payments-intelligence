-- =====================================================================================
-- 03  Load gold Parquet from S3 into Redshift (called by Step Functions / Airflow daily)
--
-- Pattern: COPY into a staging table, then swap the affected date range inside ONE
-- transaction (delete + insert). Readers never see a half-loaded day, and reruns are
-- idempotent. Small dimensions are rebuilt by dbt; this procedure owns the big facts.
-- =====================================================================================

CREATE OR REPLACE PROCEDURE core.sp_load_from_lake()
AS $$
DECLARE
    lake_root VARCHAR(256) := 's3://stablecoin-payments-dev-lake-123456789012';
    min_month DATE;
BEGIN
    -- 1. Wallet x day: COPY the most recent month partitions (gold rewrites the open month daily)
    DROP TABLE IF EXISTS staging.wallet_daily_load;
    CREATE TABLE staging.wallet_daily_load (LIKE core.fct_wallet_daily);
    EXECUTE 'COPY staging.wallet_daily_load FROM ''' || lake_root
         || '/gold/wallet_daily/block_month=' || TO_CHAR(DATEADD(day, -1, CURRENT_DATE), 'YYYY-MM')
         || '/'' IAM_ROLE default FORMAT AS PARQUET';

    SELECT MIN(DATE_TRUNC('month', activity_date)) INTO min_month FROM staging.wallet_daily_load;

    DELETE FROM core.fct_wallet_daily WHERE activity_date >= min_month;
    INSERT INTO core.fct_wallet_daily SELECT * FROM staging.wallet_daily_load;

    -- 2. Daily and hourly aggregates are small: full refresh
    TRUNCATE core.fct_network_hourly;    -- dbt rebuilds the enriched version from lake.hourly_network
    -- (dbt models core.fct_transfers_daily / fct_network_hourly read Spectrum tables directly)

    -- 3. Load audit row
    INSERT INTO staging.load_audit (loaded_at, table_name, rows_loaded)
    SELECT GETDATE(), 'fct_wallet_daily', COUNT(*) FROM staging.wallet_daily_load;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS staging.load_audit (
    loaded_at    TIMESTAMP,
    table_name   VARCHAR(64),
    rows_loaded  BIGINT
);

-- Post-load housekeeping (auto vacuum/analyze usually suffices on Serverless; explicit after backfills)
-- VACUUM SORT ONLY core.fct_wallet_daily TO 95 PERCENT;
-- ANALYZE core.fct_wallet_daily PREDICATE COLUMNS;
