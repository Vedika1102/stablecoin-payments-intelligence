select
    wallet,
    cast(first_seen_date as date)     as first_seen_date,
    cast(first_receive_date as date)  as first_receive_date,
    cast(first_send_date as date)     as first_send_date,
    cast(last_active_date as date)    as last_active_date,
    cast(active_days as integer)      as active_days,
    cast(lifetime_sent_n as bigint)   as lifetime_sent_n,
    lifetime_sent_usd,
    cast(lifetime_recv_n as bigint)   as lifetime_recv_n,
    lifetime_recv_usd,
    first_receive_usd,
    first_receive_token,
    primary_token
from {{ source('lake', 'wallet_profile') }}
