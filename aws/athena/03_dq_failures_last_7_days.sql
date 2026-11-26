-- Data quality monitor: any failed check in the last week (feeds the DQ tile in the dashboard).
SELECT run_date, dataset, check, severity, observed, threshold, partition
FROM _dq_results
WHERE NOT passed
  AND run_date >= current_date - INTERVAL '7' DAY
ORDER BY run_date DESC, severity;
