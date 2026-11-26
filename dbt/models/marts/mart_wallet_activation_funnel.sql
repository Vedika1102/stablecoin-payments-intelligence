{{ config(dist='all', sort=['cohort_month']) }}
-- Q4: new-wallet activation funnel by monthly cohort.
-- New wallet = first stablecoin activity on/after cohort_start (6-month lookback screens out
-- wallets that were simply quiet at the start of the window).
-- received -> sent within 7 days -> sent within 30 days -> active in month 1 -> active in month 3
with p as (
    select * from {{ ref('stg_wallet_profile') }}
    where first_receive_date >= cast('{{ var("cohort_start") }}' as date)
      and first_seen_date = first_receive_date           -- entered by receiving (the payout case)
),
m as (select wallet, activity_month from {{ ref('stg_wallet_monthly') }}),
base as (
    select
        p.wallet,
        cast({{ dbt.date_trunc('month', 'p.first_receive_date') }} as date) as cohort_month,
        p.primary_token,
        case when p.first_receive_usd < 100 then 'under_$100'
             when p.first_receive_usd < 1000 then '$100-1K'
             when p.first_receive_usd < 10000 then '$1K-10K'
             else '$10K+' end as first_receive_band,
        case when p.first_send_date is not null
              and {{ dbt.datediff('p.first_receive_date', 'p.first_send_date', 'day') }} <= 7 then 1 else 0 end as sent_7d,
        case when p.first_send_date is not null
              and {{ dbt.datediff('p.first_receive_date', 'p.first_send_date', 'day') }} <= 30 then 1 else 0 end as sent_30d
    from p
),
act as (
    select b.wallet,
           max(case when {{ dbt.datediff('b.cohort_month', 'm.activity_month', 'month') }} = 1 then 1 else 0 end) as active_m1,
           max(case when {{ dbt.datediff('b.cohort_month', 'm.activity_month', 'month') }} = 3 then 1 else 0 end) as active_m3
    from base b join m on m.wallet = b.wallet
    group by b.wallet
)
select
    b.cohort_month, b.primary_token, b.first_receive_band,
    count(*)                          as new_wallets,
    sum(b.sent_7d)                    as sent_within_7d,
    sum(b.sent_30d)                   as sent_within_30d,
    sum(coalesce(a.active_m1, 0))     as active_month_1,
    sum(coalesce(a.active_m3, 0))     as active_month_3,
    -- month 3 is only observable for cohorts at least 3 full months before the window end
    case when {{ dbt.dateadd('month', 3, 'b.cohort_month') }} <= cast('{{ var("window_end") }}' as date)
         then true else false end     as month_3_observed
from base b
left join act a on a.wallet = b.wallet
group by 1, 2, 3, 9
