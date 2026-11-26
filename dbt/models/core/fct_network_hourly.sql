{{ config(dist='all', sort=['hour_ts']) }}
select
    n.hour_ts,
    cast(n.hour_ts as date)                 as activity_date,
    extract(hour from n.hour_ts)            as hour_of_day,
    d.day_of_week,
    d.protocol_era,
    n.avg_base_fee_gwei,
    n.avg_block_utilization,
    n.network_tx_count,
    n.blocks,
    n.eth_usd,
    n.oracle_swaps,
    -- USD cost of one ERC-20 transfer (65k gas) at the hour's average base fee
    n.avg_base_fee_gwei * 1e-9 * 65000 * n.eth_usd as est_transfer_fee_usd
from {{ ref('stg_hourly_network') }} n
left join {{ ref('dim_date') }} d on d.date_day = cast(n.hour_ts as date)
