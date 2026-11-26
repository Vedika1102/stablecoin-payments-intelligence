{{ config(dist='wallet', sort=['wallet', 'valid_from']) }}
{#-
  SCD Type 2 wallet dimension. The tracked attribute is the behavioural segment, re-scored every
  month in the gold layer. Consecutive months with the same segment collapse into one version
  (gaps-and-islands), so a wallet that moves payment_like -> high_throughput_service -> payment_like
  has three versions. Type 1 attributes (first seen, primary token) are the same on every version.
-#}
with m as (
    select wallet, activity_month, segment from {{ ref('stg_wallet_monthly') }}
),
flagged as (
    select *,
           case when lag(segment) over (partition by wallet order by activity_month) = segment
                then 0 else 1 end as is_new_version
    from m
),
numbered as (
    select *,
           sum(is_new_version) over (partition by wallet order by activity_month
                                     rows between unbounded preceding and current row) as version_no
    from flagged
),
versions as (
    select wallet, version_no, segment, min(activity_month) as valid_from, count(*) as months_in_version
    from numbered
    group by wallet, version_no, segment
),
bounded as (
    select *,
           lead(valid_from) over (partition by wallet order by valid_from) as next_from
    from versions
)
select
    {{ surrogate_key(['b.wallet', 'b.valid_from']) }}                  as wallet_key,
    b.wallet,
    b.segment,
    b.version_no,
    b.months_in_version,
    b.valid_from,
    coalesce(cast({{ dbt.dateadd('day', -1, 'b.next_from') }} as date), cast('9999-12-31' as date)) as valid_to,
    case when b.next_from is null then true else false end            as is_current,
    p.first_seen_date,
    p.first_receive_date,
    p.first_send_date,
    p.primary_token,
    case when p.first_seen_date >= cast('{{ var("cohort_start") }}' as date) then true else false end
                                                                      as is_new_in_window
from bounded b
left join {{ ref('stg_wallet_profile') }} p on p.wallet = b.wallet
