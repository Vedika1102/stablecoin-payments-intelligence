-- =====================================================================================
-- 05  Performance checks and monitoring queries
-- =====================================================================================

-- Is the wallet join co-located? Look for DS_DIST_NONE (good) vs DS_BCAST/DS_DIST_BOTH (bad).
EXPLAIN
SELECT w.segment, SUM(m.sent_usd)
FROM core.fct_wallet_monthly m
JOIN core.dim_wallet w
  ON w.wallet = m.wallet AND m.activity_month BETWEEN w.valid_from AND w.valid_to
GROUP BY 1;

-- Table health: skew across slices, unsorted %, stats staleness
SELECT "table", diststyle, sortkey1, skew_rows, unsorted, stats_off, tbl_rows, size AS size_mb
FROM svv_table_info
WHERE "schema" IN ('core', 'marts')
ORDER BY size DESC;

-- Spectrum usage in the last day: partitions pruned, files read (Serverless SYS_* view)
SELECT query_id, source_type, total_partitions, qualified_partitions, scanned_files,
       returned_rows, ROUND(returned_bytes / 1e6, 1) AS mb_returned, duration / 1000 AS ms
FROM sys_external_query_detail
WHERE start_time >= DATEADD(day, -1, GETDATE())
ORDER BY returned_bytes DESC
LIMIT 20;

-- Slowest dashboard queries (Serverless)
SELECT query_id, elapsed_time / 1e6 AS seconds, LEFT(query_text, 120) AS sql
FROM sys_query_history
WHERE start_time >= DATEADD(day, -1, GETDATE()) AND status = 'success'
ORDER BY elapsed_time DESC
LIMIT 20;

-- COPY failures
SELECT query_id, file_name, line_number, column_name, error_message
FROM sys_load_error_detail
WHERE start_time >= DATEADD(day, -1, GETDATE());
