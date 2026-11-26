{{ config(dist='all') }}
select
    {{ surrogate_key(['token_address']) }} as token_key,
    token_address, symbol as token_symbol, issuer, decimals, peg,
    cast(launched_on_ethereum as date) as launched_on_ethereum
from {{ ref('dim_token_seed') }}
