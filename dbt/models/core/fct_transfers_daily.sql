{{ config(dist='all', sort=['activity_date']) }}
-- Daily transfer aggregate (grain: date x token x ticket bucket x kind x flow type).
select
    k.activity_date,
    t.token_key,
    k.token_symbol,
    k.ticket_bucket,
    k.transfer_kind,
    k.flow_type,
    case
        when k.transfer_kind <> 'transfer'                               then 'mint_burn'
        when k.ticket_bucket = '0_dust_<$0.01'                           then 'dust_spam'
        when k.flow_type = 'eoa_to_eoa' and b.is_small_ticket            then 'p2p_small_ticket'
        when k.flow_type = 'eoa_to_eoa'                                  then 'p2p_large_ticket'
        else 'contract_flow'
    end                                     as flow_category,
    k.transfers, k.volume_usd, k.senders_approx, k.receivers_approx,
    k.avg_base_fee_gwei, k.median_fee_usd, k.median_amount_usd
from {{ ref('stg_daily_kpis') }} k
left join {{ ref('dim_token') }} t on t.token_symbol = k.token_symbol
left join {{ ref('dim_ticket_bucket') }} b on b.ticket_bucket = k.ticket_bucket
