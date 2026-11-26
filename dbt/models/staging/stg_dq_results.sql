select dataset, "check" as check_name, severity, passed, observed, threshold, "partition" as partition_label,
       cast(run_ts as timestamp) as run_ts
from {{ source('lake', 'dq_results') }}
