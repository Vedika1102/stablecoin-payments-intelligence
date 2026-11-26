-- Every hour in the window has network data (gaps would bias the fee elasticity model).
with hours as (
    select count(*) as n, min(hour_ts) as lo, max(hour_ts) as hi from {{ ref('fct_network_hourly') }}
)
select * from hours
where n <> {{ dbt.datediff('lo', 'hi', 'hour') }} + 1
