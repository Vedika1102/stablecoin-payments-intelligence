select
    cast(block_date as date)          as activity_date,
    token_symbol,
    ticket_bucket,
    transfer_kind,
    flow_type,
    cast(transfers as bigint)         as transfers,
    cast(volume_usd as double)        as volume_usd,
    cast(senders_approx as bigint)    as senders_approx,
    cast(receivers_approx as bigint)  as receivers_approx,
    avg_base_fee_gwei,
    median_fee_usd,
    median_amount_usd
from {{ source('lake', 'daily_kpis') }}
