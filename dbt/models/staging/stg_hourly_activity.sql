select
    cast(hour_ts as timestamp)   as hour_ts,
    token_symbol,
    ticket_bucket,
    cast(transfers as bigint)    as transfers,
    cast(volume_usd as {{ dbt.type_float() }})   as volume_usd,
    avg_base_fee_gwei,
    avg_fee_usd
from {{ source('lake', 'hourly_activity') }}
