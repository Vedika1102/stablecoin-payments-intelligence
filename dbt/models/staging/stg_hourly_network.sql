select
    cast(hour_ts as timestamp)         as hour_ts,
    avg_base_fee_gwei,
    avg_block_utilization,
    cast(network_tx_count as bigint)   as network_tx_count,
    cast(blocks as integer)            as blocks,
    eth_usd,
    cast(swaps as integer)             as oracle_swaps
from {{ source('lake', 'hourly_network') }}
