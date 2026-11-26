{{ config(dist='all', sort=['activity_date']) }}
-- Q1: how much stablecoin activity looks like payments? Daily mix by flow category and token.
select
    f.activity_date,
    d.protocol_era,
    f.token_symbol,
    f.flow_category,
    sum(f.transfers)  as transfers,
    sum(f.volume_usd) as volume_usd,
    sum(f.transfers * f.median_fee_usd) / nullif(sum(f.transfers), 0) as avg_median_fee_usd
from {{ ref('fct_transfers_daily') }} f
left join {{ ref('dim_date') }} d on d.date_day = f.activity_date
group by 1, 2, 3, 4
