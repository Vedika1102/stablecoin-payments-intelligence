-- Query the AWS Public Blockchain bucket in place (no copy) through the Glue table with
-- partition projection. Always filter on `date` so Athena prunes partitions: this query scans
-- ~1 day (~0.1-0.4 GB) instead of the full table (TBs).
SELECT
    CASE token_address
        WHEN '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48' THEN 'USDC'
        WHEN '0xdac17f958d2ee523a2206206994597c13d831ec7' THEN 'USDT'
    END                                  AS token,
    COUNT(*)                             AS transfers,
    SUM(value) / 1e6                     AS volume_usd,
    APPROX_DISTINCT(from_address)        AS senders
FROM public_eth.token_transfers
WHERE date = '2024-03-13'
  AND token_address IN ('0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                        '0xdac17f958d2ee523a2206206994597c13d831ec7')
GROUP BY 1;
