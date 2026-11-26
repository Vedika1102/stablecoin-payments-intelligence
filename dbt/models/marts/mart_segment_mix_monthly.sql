{{ config(dist='all', sort=['activity_month']) }}
-- Q1/Q5: wallets and value by behavioural segment and month.
select
    activity_month,
    segment,
    count(*)                            as wallets,
    sum(sent_n)                         as transfers_sent,
    sum(sent_usd)                       as volume_sent_usd,
    sum(sent_small_n)                   as small_ticket_sent,
    sum(case when usdc_n >= usdt_n then 1 else 0 end) as usdc_primary_wallets
from {{ ref('fct_wallet_monthly') }}
group by 1, 2
