{{ config(materialized='view') }}
-- Transfer-level detail stays in the lake (Spectrum external table in prod). Views only.
select
    cast(block_date as date) as block_date, block_timestamp, hour_ts, block_number, transaction_hash, log_index,
    token_symbol, from_address, to_address, amount_usd, ticket_bucket, transfer_kind, flow_type,
    from_is_contract, to_is_contract, base_fee_gwei, eth_usd, est_fee_usd, fee_to_amount_bps
from {{ source('lake', 'stablecoin_transfers') }}
