-- Data quality scorecard for the dashboard: every check ever run, latest result per check/partition.
with r as (
    select *, row_number() over (partition by dataset, check_name, partition_label order by run_ts desc) as rn
    from {{ ref('stg_dq_results') }}
)
select dataset, check_name, severity, passed, observed, threshold, partition_label, run_ts
from r where rn = 1
