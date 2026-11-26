-- =====================================================================================
-- 01  Redshift Spectrum: query the S3 lake (and the public dataset) in place
-- Transfer-level detail (~300M rows for two years, billions for full history) stays in S3
-- as Parquet. Redshift stores only the aggregates and dimensions that dashboards hit hard.
-- =====================================================================================

-- Our lake (bronze/silver/gold), catalogued by the Glue crawler
CREATE EXTERNAL SCHEMA IF NOT EXISTS lake
FROM DATA CATALOG
DATABASE 'stablecoin_payments_dev_lake'
IAM_ROLE default
REGION 'us-east-2';

-- The AWS Public Blockchain dataset itself (Glue tables with partition projection, see Terraform)
CREATE EXTERNAL SCHEMA IF NOT EXISTS public_eth
FROM DATA CATALOG
DATABASE 'stablecoin_payments_dev_public_eth'
IAM_ROLE default
REGION 'us-east-2';

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS staging;

-- Spectrum sanity check: partition pruning keeps this to one day of Parquet
SELECT token_symbol, COUNT(*) AS transfers, SUM(amount_usd) AS volume_usd
FROM lake.stablecoin_transfers
WHERE block_date = '2024-03-13'
GROUP BY 1;
