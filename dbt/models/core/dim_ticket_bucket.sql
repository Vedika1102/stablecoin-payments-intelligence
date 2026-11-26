{{ config(dist='all') }}
select ticket_bucket, label, lower_usd, upper_usd, is_small_ticket, sort_order
from {{ ref('ticket_buckets') }}
