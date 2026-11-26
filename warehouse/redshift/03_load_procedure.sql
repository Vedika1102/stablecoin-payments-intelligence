-- =====================================================================================
-- 03  Load gold Parquet from S3 into Redshift (called by Step Functions / Airflow daily)
--
-- Pattern: COPY one month of Parquet into a raw staging table that mirrors the file layout,
-- then swap that month inside ONE transaction (delete + insert). Readers never see a
-- half-loaded month and reruns are idempotent. Small tables are rebuilt by dbt.
--
-- Usage:
--   CALL core.sp_load_from_lake('s3://stablecoin-payments-dev-lake-<account id>', '2024-03');
--   CALL core.sp_load_from_lake('s3://...', NULL);   -- NULL = the month of yesterday (daily run)
-- =====================================================================================

CREATE TABLE IF NOT EXISTS staging.load_audit (
    loaded_at    TIMESTAMP,
    table_name   VARCHAR(64),
    load_month   CHAR(7),
    rows_loaded  BIGINT
);

-- Mirrors the Parquet columns in file order (COPY maps Parquet columns by position).
-- first_recv is a nested struct; SERIALIZETOJSON lands it in a SUPER column.
CREATE TABLE IF NOT EXISTS staging.wallet_daily_raw (
    wallet              VARCHAR(42),
    block_date          DATE,
    sent_n              BIGINT,
    sent_usd            DOUBLE PRECISION,
    recv_n              BIGINT,
    recv_usd            DOUBLE PRECISION,
    sent_small_n        BIGINT,
    sent_to_contract_n  BIGINT,
    counterparties_out  BIGINT,
    counterparties_in   BIGINT,
    usdc_n              BIGINT,
    usdt_n              BIGINT,
    dai_n               BIGINT,
    pyusd_n             BIGINT,
    max_sent_usd        DOUBLE PRECISION,
    first_recv          SUPER
);

CREATE OR REPLACE PROCEDURE core.sp_load_from_lake(lake_root VARCHAR(256), load_month VARCHAR(7))
AS $$
DECLARE
    m        VARCHAR(7);
    n_rows   BIGINT;
BEGIN
    m := COALESCE(load_month, TO_CHAR(DATEADD(day, -1, CURRENT_DATE), 'YYYY-MM'));

    TRUNCATE staging.wallet_daily_raw;
    EXECUTE 'COPY staging.wallet_daily_raw FROM ''' || lake_root || '/gold/wallet_daily/block_month=' || m
         || '/'' IAM_ROLE default FORMAT AS PARQUET SERIALIZETOJSON';

    SELECT COUNT(*) INTO n_rows FROM staging.wallet_daily_raw;
    IF n_rows = 0 THEN
        RAISE EXCEPTION 'No rows in gold/wallet_daily for %', m;
    END IF;

    DELETE FROM core.fct_wallet_daily
    WHERE activity_date >= TO_DATE(m || '-01', 'YYYY-MM-DD')
      AND activity_date <  DATEADD(month, 1, TO_DATE(m || '-01', 'YYYY-MM-DD'));

    INSERT INTO core.fct_wallet_daily
    SELECT wallet, block_date, sent_n, sent_usd, recv_n, recv_usd, sent_small_n, sent_to_contract_n,
           counterparties_out, counterparties_in, usdc_n, usdt_n, dai_n, pyusd_n, max_sent_usd
    FROM staging.wallet_daily_raw;

    INSERT INTO staging.load_audit VALUES (GETDATE(), 'fct_wallet_daily', m, n_rows);
END;
$$ LANGUAGE plpgsql;

-- Post-load housekeeping (auto vacuum/analyze usually suffices on Serverless; explicit after backfills)
-- VACUUM SORT ONLY core.fct_wallet_daily TO 95 PERCENT;
-- ANALYZE core.fct_wallet_daily PREDICATE COLUMNS;
