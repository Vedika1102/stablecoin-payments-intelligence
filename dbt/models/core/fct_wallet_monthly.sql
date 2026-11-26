{{ config(dist='wallet', sort=['activity_month']) }}
-- Periodic snapshot: wallet x month, carrying the wallet version valid that month.
with m as (select * from {{ ref('stg_wallet_monthly') }}),
w as (select wallet, wallet_key, valid_from, valid_to from {{ ref('dim_wallet') }}),
p as (select wallet, first_seen_date from {{ ref('stg_wallet_profile') }})
select
    {{ surrogate_key(['m.wallet', 'm.activity_month']) }}  as wallet_month_key,
    w.wallet_key,
    m.wallet,
    m.activity_month,
    {{ dbt.datediff(dbt.date_trunc('month', 'p.first_seen_date'), 'm.activity_month', 'month') }} as months_since_first_seen,
    m.segment,
    m.active_days, m.sent_n, m.sent_usd, m.recv_n, m.recv_usd, m.sent_small_n,
    m.to_contract_share, m.avg_ticket_sent, m.counterparties_out, m.counterparties_in, m.usdc_n, m.usdt_n
from m
join w on w.wallet = m.wallet and m.activity_month between w.valid_from and w.valid_to
left join p on p.wallet = m.wallet
