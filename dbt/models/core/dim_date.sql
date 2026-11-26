{{ config(dist='all', sort=['date_day']) }}
-- Calendar built from a digits cross join so it runs unchanged on Redshift and DuckDB.
with digits as (
    select 0 as n union all select 1 union all select 2 union all select 3 union all select 4
    union all select 5 union all select 6 union all select 7 union all select 8 union all select 9
),
numbers as (
    select a.n + 10 * b.n + 100 * c.n + 1000 * d.n as n
    from digits a cross join digits b cross join digits c cross join digits d
),
days as (
    select cast({{ dbt.dateadd('day', 'n', "cast('2023-01-01' as date)") }} as date) as date_day from numbers
)
select
    d.date_day,
    cast({{ dbt.date_trunc('week', 'd.date_day') }} as date)   as week_start,
    cast({{ dbt.date_trunc('month', 'd.date_day') }} as date)  as month_start,
    extract(year from d.date_day)                              as year_number,
    extract(dow from d.date_day)                               as day_of_week,
    case when extract(dow from d.date_day) in (0, 6) then true else false end as is_weekend,
    e.era                                                      as protocol_era
from days d
left join {{ ref('protocol_eras') }} e
  on d.date_day between cast(e.start_date as date) and cast(e.end_date as date)
where d.date_day <= cast('2026-12-31' as date)
