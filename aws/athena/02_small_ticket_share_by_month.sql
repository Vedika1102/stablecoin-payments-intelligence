-- Share of person-to-person stablecoin transfers under $1,000, by month (silver layer).
SELECT DATE_TRUNC('month', CAST(block_date AS date))                     AS month,
       token_symbol,
       COUNT(*)                                                          AS p2p_transfers,
       AVG(CASE WHEN amount_usd < 1000 THEN 1.0 ELSE 0.0 END)            AS small_ticket_share,
       APPROX_PERCENTILE(est_fee_usd, 0.5)                               AS median_fee_usd
FROM stablecoin_transfers
WHERE transfer_kind = 'transfer'
  AND flow_type = 'eoa_to_eoa'
  AND block_date BETWEEN '2024-01-01' AND '2024-06-30'
GROUP BY 1, 2
ORDER BY 1, 2;
