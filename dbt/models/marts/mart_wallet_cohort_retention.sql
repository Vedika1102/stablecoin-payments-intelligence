{{ config(dist='all', sort=['cohort_month', 'months_since_start']) }}
-- Q4: survival-style retention: share of a new-wallet cohort active in month k.
with p as (
    select wallet, primary_token,
           cast({{ dbt.date_trunc('month', 'first_seen_date') }} as date) as cohort_month
    from {{ ref('stg_wallet_profile') }}
    where first_seen_date >= cast('{{ var("cohort_start") }}' as date)
),
sizes as (select cohort_month, primary_token, count(*) as cohort_size from p group by 1, 2),
act as (
    select p.cohort_month, p.primary_token,
           {{ dbt.datediff('p.cohort_month', 'm.activity_month', 'month') }} as months_since_start,
           count(*) as active_wallets
    from p join {{ ref('stg_wallet_monthly') }} m on m.wallet = p.wallet
    group by 1, 2, 3
)
select a.cohort_month, a.primary_token, a.months_since_start, s.cohort_size, a.active_wallets,
       {{ safe_divide('a.active_wallets', 's.cohort_size') }} as retention_rate
from act a
join sizes s on s.cohort_month = a.cohort_month and s.primary_token = a.primary_token
