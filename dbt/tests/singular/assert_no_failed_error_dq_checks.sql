-- The warehouse refuses to build on top of a lake partition whose latest error-level DQ check failed.
select * from {{ ref('mart_dq_summary') }} where severity = 'error' and not passed
