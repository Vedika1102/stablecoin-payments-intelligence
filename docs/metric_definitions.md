# Metric definitions

Every number in the dashboard and memo comes from one of these definitions. Each metric names its
source table, so a reviewer can trace it to SQL.

## Scope

| Term | Definition |
|---|---|
| Stablecoin | USDC, USDT, DAI and PYUSD on Ethereum mainnet (`config/tokens.csv`). All four are treated as $1.00. A de-peg would break `amount_usd`, so it's flagged as a known limitation. |
| Transfer | One ERC-20 `Transfer` event (`transaction_hash` + `log_index`). One transaction can contain several transfers. |
| Window | 2023-07-01 to 2025-06-30, UTC days. |
| Wallet (EOA) | An address that is not in the contract registry (no contract was ever created at it). Usually a person, a business key or a bot. |
| Contract | An address in the registry built from the public `contracts` table: DEX pools, exchange and bridge contracts, smart-contract wallets. |

## Transfer classification (`core.fct_transfers_daily.flow_category`)

| Category | Rule |
|---|---|
| `mint_burn` | `from` or `to` is the zero address (the issuer creating or redeeming tokens). |
| `dust_spam` | Under $0.01. Almost all of these are zero-value "address poisoning" transfers: an attacker emits a fake transfer from a look-alike address so it shows up in the victim's history, hoping the victim copies it next time. In July 2023 they were ~16% of all wallet-to-wallet USDT/USDC transfers. Excluded from every payment metric. |
| `p2p_small_ticket` | Wallet to wallet (both sides EOAs) and under $1,000. **This is the payment-like flow.** |
| `p2p_large_ticket` | Wallet to wallet, $1,000 or more. |
| `contract_flow` | At least one side is a contract. |

Ticket buckets: under $0.01 (spam), $0.01 to $10, $10 to 100, $100 to 1K, $1K to 10K, $10K to 100K, $100K and up (`dim_ticket_bucket`).

## Fees

| Metric | Definition | Source |
|---|---|---|
| Base fee (gwei) | Protocol base fee per gas of the block containing the transfer. | `bronze.blocks.base_fee_per_gas / 1e9` |
| ETH/USD | Hourly median price implied by swaps in the Uniswap v3 USDC/WETH 0.05% pool: USDC leg / WETH leg per swap transaction, ignoring dust trades (< $50 or < 0.02 ETH). No off-chain price feed. | `silver.eth_usd_hourly` |
| Est. transfer fee (USD) | `base_fee_gwei x 1e-9 x 65,000 gas x ETH/USD`. 65k gas is a typical USDC/USDT transfer. Excludes the priority tip, so it's a lower bound. | `silver.stablecoin_transfers.est_fee_usd` |
| Fee-to-amount (bps) | `est_fee_usd / amount_usd x 10,000`. | silver |

## Wallet lifecycle

| Metric | Definition |
|---|---|
| New wallet | First stablecoin activity on or after **2024-01-01**. The window starts 2023-07-01, so every new wallet has at least 6 months of lookback, which screens out wallets that were simply quiet. Wallets in the funnel must *enter by receiving* (first activity = first receipt), which is the payout scenario. |
| Cohort month | Month of first receipt. |
| Activation (7-day) | Wallet sends any stablecoin within 7 days of its first receipt. |
| Active in month k | Wallet has at least one send or receive in calendar month `cohort_month + k`. |
| Month-3 retention | Active in month 3. Only cohorts whose month 3 ends on or before the window end count in the denominator (right-censoring). |
| Survival (KM) | Duration = months from first receipt to last activity. Churned = no activity in the final 60 days of the window; otherwise censored. |

## Behavioural segments (`gold.wallet_monthly.segment`, SCD2 in `core.dim_wallet`)

Each wallet is scored every month it is active. The first matching rule wins:

1. `high_throughput_service`: 100+ distinct counterparties, or 500+ transfers in the month (exchange hot wallets, payment processors, bots).
2. `receive_only`: received but sent nothing.
3. `defi_contract_user`: 50%+ of sends go to contracts.
4. `large_value_mover`: average send of $100K or more.
5. `payment_like`: average send under $10K and at most 20 distinct recipients.
6. `other`: anything else.

The counterparty counts are summed daily approximate distinct counts (HyperLogLog), so the monthly figure is an upper bound. That's conservative for rule 1. The thresholds are judgment calls, so they're documented here and treated as parameters.

## Statistical conventions

* Two-sided tests, alpha = 0.05, with 95% confidence intervals on every effect.
* With tens of millions of rows, almost every difference is "significant". Effect sizes (Cohen's h, Cramer's V, odds ratios, elasticities) are what the memo reports.
* Hourly time series use Newey-West (HAC) standard errors because of autocorrelation.
* Holm correction when several segment comparisons are read together.
