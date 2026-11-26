-- Every wallet-month in the snapshot resolves to exactly one SCD2 version (no gaps, no overlaps).
select m.wallet, m.activity_month, count(w.wallet_key) as versions
from {{ ref('stg_wallet_monthly') }} m
left join {{ ref('dim_wallet') }} w
  on w.wallet = m.wallet and m.activity_month between w.valid_from and w.valid_to
group by 1, 2
having count(w.wallet_key) <> 1
