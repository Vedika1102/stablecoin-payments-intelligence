-- =====================================================================================
-- 04  Analytical SQL behind the memo and dashboard (Redshift dialect)
-- =====================================================================================

-- Q1. Payment-like share of transfers, monthly, with month-over-month change
WITH m AS (
    SELECT DATE_TRUNC('month', activity_date) AS month,
           SUM(CASE WHEN flow_category = 'p2p_small_ticket' THEN transfers ELSE 0 END) AS p2p_small,
           SUM(transfers) AS total
    FROM core.fct_transfers_daily
    GROUP BY 1
)
SELECT month,
       p2p_small::FLOAT / total AS p2p_small_share,
       p2p_small::FLOAT / total - LAG(p2p_small::FLOAT / total) OVER (ORDER BY month) AS mom_change
FROM m
ORDER BY month;

-- Q2. Fee elasticity, binned: small-ticket P2P transfers per hour by fee decile
WITH h AS (
    SELECT n.hour_ts, n.est_transfer_fee_usd,
           NTILE(10) OVER (ORDER BY n.est_transfer_fee_usd) AS fee_decile,
           p.p2p_small_transfers
    FROM core.fct_network_hourly n
    JOIN marts.mart_fee_hourly_panel p USING (hour_ts)
    WHERE n.protocol_era = 'pre_dencun'
)
SELECT fee_decile,
       MIN(est_transfer_fee_usd) AS fee_from, MAX(est_transfer_fee_usd) AS fee_to,
       AVG(p2p_small_transfers)  AS avg_small_transfers_per_hour
FROM h
GROUP BY 1
ORDER BY 1;

-- Q3. Dencun pre/post comparison of small vs large ticket P2P (the 2x2 behind the diff-in-diff)
SELECT protocol_era,
       AVG(p2p_small_transfers) AS small_per_hour,
       AVG(p2p_large_transfers) AS large_per_hour,
       AVG(est_transfer_fee_usd) AS fee_usd
FROM marts.mart_fee_hourly_panel
WHERE hour_ts BETWEEN DATEADD(day, -90, '2024-03-13') AND DATEADD(day, 90, '2024-03-13')
GROUP BY 1;

-- Q4. Cohort retention triangle (months 0..6), USDC vs USDT
SELECT cohort_month, primary_token,
       MAX(CASE WHEN months_since_start = 1 THEN retention_rate END) AS m1,
       MAX(CASE WHEN months_since_start = 3 THEN retention_rate END) AS m3,
       MAX(CASE WHEN months_since_start = 6 THEN retention_rate END) AS m6
FROM marts.mart_wallet_cohort_retention
GROUP BY 1, 2
ORDER BY 1, 2;

-- Q5. Segment migration: how wallets move between segments month to month (SCD2 history)
SELECT prev_segment, segment, COUNT(*) AS wallets
FROM (
    SELECT wallet, segment,
           LAG(segment) OVER (PARTITION BY wallet ORDER BY valid_from) AS prev_segment
    FROM core.dim_wallet
) t
WHERE prev_segment IS NOT NULL
GROUP BY 1, 2
ORDER BY wallets DESC;

-- Q6. Top 20 payment-like wallets by monthly volume, latest month (QUALIFY)
SELECT activity_month, wallet, sent_usd, sent_n
FROM core.fct_wallet_monthly
WHERE segment = 'payment_like'
  AND activity_month = (SELECT MAX(activity_month) FROM core.fct_wallet_monthly)
QUALIFY ROW_NUMBER() OVER (ORDER BY sent_usd DESC) <= 20;

-- Q7. Spectrum + local join: hourly fee context for transfers of one wallet, straight from S3
SELECT t.block_timestamp, t.token_symbol, t.amount_usd, t.est_fee_usd, w.segment
FROM lake.stablecoin_transfers t
JOIN core.dim_wallet w
  ON w.wallet = t.from_address
 AND t.block_date BETWEEN w.valid_from AND w.valid_to
WHERE t.block_date BETWEEN '2024-03-01' AND '2024-03-31'
  AND t.from_address = '0x0000000000000000000000000000000000000001';

-- Q8. Materialized view for the dashboard's daily KPI tile, refreshed automatically
CREATE MATERIALIZED VIEW marts.mv_daily_kpis
AUTO REFRESH YES
AS
SELECT activity_date, token_symbol, flow_category,
       SUM(transfers) AS transfers, SUM(volume_usd) AS volume_usd
FROM core.fct_transfers_daily
GROUP BY 1, 2, 3;
