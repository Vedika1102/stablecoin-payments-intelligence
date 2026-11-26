select
    wallet,
    cast(block_month || '-01' as date)    as activity_month,
    cast(active_days as integer)          as active_days,
    cast(sent_n as integer)               as sent_n,
    sent_usd,
    cast(recv_n as integer)               as recv_n,
    recv_usd,
    cast(sent_small_n as integer)         as sent_small_n,
    to_contract_share,
    avg_ticket_sent,
    cast(counterparties_out as integer)   as counterparties_out,
    cast(counterparties_in as integer)    as counterparties_in,
    cast(usdc_n as integer)               as usdc_n,
    cast(usdt_n as integer)               as usdt_n,
    segment
from {{ source('lake', 'wallet_monthly') }}
