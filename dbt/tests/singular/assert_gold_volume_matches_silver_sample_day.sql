-- Reconciliation: for one fixed day, the gold daily aggregate equals a direct count over the
-- transfer-level silver data (catches aggregation bugs without scanning all 300M rows).
with g as (
    select sum(transfers) as n, sum(volume_usd) as v
    from {{ ref('fct_transfers_daily') }} where activity_date = cast('2024-03-13' as date)
),
s as (
    select count(*) as n, sum(amount_usd) as v
    from {{ ref('stg_stablecoin_transfers') }} where block_date = cast('2024-03-13' as date)
)
select * from g, s where g.n <> s.n or abs(g.v - s.v) > 0.01 * s.v / 1e4
