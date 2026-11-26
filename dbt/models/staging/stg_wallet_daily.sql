select
    wallet,
    cast(block_date as date)              as activity_date,
    cast(sent_n as integer)               as sent_n,
    sent_usd,
    cast(recv_n as integer)               as recv_n,
    recv_usd,
    cast(sent_small_n as integer)         as sent_small_n,
    cast(sent_to_contract_n as integer)   as sent_to_contract_n,
    cast(counterparties_out as integer)   as counterparties_out,
    cast(counterparties_in as integer)    as counterparties_in,
    cast(usdc_n as integer)               as usdc_n,
    cast(usdt_n as integer)               as usdt_n,
    cast(dai_n as integer)                as dai_n,
    cast(pyusd_n as integer)              as pyusd_n,
    max_sent_usd
from {{ source('lake', 'wallet_daily') }}
