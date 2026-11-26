{{ config(dist='all', sort=['hour_ts']) }}
-- Q2/Q3: hourly panel for fee elasticity and the Dencun diff-in-diff.
-- Small tickets (< $1K) are the fee-sensitive group; large tickets ($10K+) the comparison group.
with a as (
    select
        h.hour_ts,
        sum(case when b.is_small_ticket then h.transfers else 0 end)                         as p2p_small_transfers,
        sum(case when h.ticket_bucket in ('e_$10K-100K', 'f_$100K+') then h.transfers else 0 end) as p2p_large_transfers,
        sum(case when h.ticket_bucket = 'a_<$10' then h.transfers else 0 end)                as p2p_micro_transfers,
        sum(h.transfers)                                                                      as p2p_transfers,
        sum(h.volume_usd)                                                                     as p2p_volume_usd
    from {{ ref('stg_hourly_activity') }} h
    join {{ ref('dim_ticket_bucket') }} b on b.ticket_bucket = h.ticket_bucket
    group by 1
)
select n.*, coalesce(a.p2p_small_transfers, 0) as p2p_small_transfers,
       coalesce(a.p2p_large_transfers, 0) as p2p_large_transfers,
       coalesce(a.p2p_micro_transfers, 0) as p2p_micro_transfers,
       coalesce(a.p2p_transfers, 0) as p2p_transfers,
       coalesce(a.p2p_volume_usd, 0) as p2p_volume_usd
from {{ ref('fct_network_hourly') }} n
left join a on a.hour_ts = n.hour_ts
