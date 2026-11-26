# Stablecoin payments on Ethereum: what the data says

**To:** Payments product and strategy leadership
**Data:** every USDC, USDT, DAI and PYUSD transfer on Ethereum mainnet, Jul 2023 to Jun 2025
(215M transfers, $19.8T moved), from the AWS Public Blockchain dataset. 1.01B token transfers scanned.
**Detail:** `reports/q1` to `q4`, metric definitions in `docs/metric_definitions.md`.

## Bottom line
1. **Payments are a large share of transfers but a rounding error in value.** Wallet-to-wallet transfers
   under $1K are 27.7% of all stablecoin transfers but 0.07% of the dollars moved. Measured by value,
   Ethereum stablecoins are a settlement and trading rail, not a consumer payments rail.
2. **Small payments are fee-sensitive, large ones are not.** Holding demand fixed, a 10% higher network
   fee goes with 1.5% fewer small transfers in that hour (elasticity -0.149, 95% CI -0.163 to -0.135).
   Relative to large transfers the gap is -0.241 (CI -0.265 to -0.217). The under-$1K share of P2P drops
   from 62% in cheap hours to 47% in the most expensive decile.
3. **"Activation" as usually defined rewards churn.** 71% of new wallets send within 7 days of their first
   receipt, but 80% of those are pass-through wallets that forward everything within 3 active days, and
   only 5% of them are active 60 days later. Activated wallets that keep a balance: 60%.
4. **We could not show a causal Dencun effect, and we say so.** The difference-in-differences around the
   March 2024 upgrade is not significant (p = 0.09), pre-trends drift and a placebo date shows a
   similar-sized effect. The fee elasticity in (2) is the evidence to rely on.

## Recommendations
| # | Recommendation | Evidence | How we'd measure it |
|---|---|---|---|
| 1 | Route small-ticket payouts (under $1K) to the cheapest available rail, and batch or delay them when mainnet fees are in the top two deciles. | Elasticity -0.149; small share falls 15 pp across fee deciles. | Share of small payouts sent in top-decile fee hours; cost per payout. |
| 2 | Redefine activation as "sent within 7 days **and** still holds a balance", and report pass-through wallets as their own segment. | Pass-through wallets are 80% of activated wallets with 5% 60-day activity, against 60% for holders. In a model without the flag, activation even looks like it predicts churn (odds ratio 0.55); with it, the sign flips (1.51). | Month-3 retention of the redefined activated group, by cohort. |
| 3 | Focus retention work on wallets whose first receipt is $100 or more. | Odds of month-3 retention are 1.5x to 2.3x higher than for first receipts under $100, holding token and activation fixed. | Retention by first-receipt band, monthly. |
| 4 | Treat USDT as the default for payment-like flows and USDC as the default for DeFi-connected users. | 34% of USDT transfers are small P2P vs 18% for USDC (Cohen's h 0.35). USDC wallets are 50% of DeFi-contract users vs 28% of payment-like wallets. | Token mix by segment, quarterly. |
| 5 | Filter address-poisoning spam before any payment metric. | 11.9M sub-cent spam transfers (5.5% of all), peaking in 2025; left in, they inflate small payments and create fake "new wallets". | Spam share on the DQ dashboard, alert above 10%. |

## What's measured, and the caveats
* **Fees** are a lower bound: base fee x 65k gas x on-chain ETH/USD (no priority tip).
* **Wallets** are externally owned addresses, not people. One person can control many; an exchange
  controls millions of deposit addresses. That is exactly why the pass-through split matters.
* **Segments** are rule-based and documented; thresholds are parameters, not truths.
* **Mainnet only.** After Dencun much small-payment activity moved to rollups (Base, Arbitrum), which this
  dataset does not cover. Conclusions are about mainnet.
* **All four tokens are valued at $1.** A de-peg would need a price series per token.

## Data quality
717 automated checks across bronze, silver and gold, all passing (`reports/pipeline_run.md`). Gold
reconciles to silver exactly on row count, and within $0.53 on $19.8T of volume (floating-point sums).
63 of 63 dbt models and tests pass, including SCD2 no-overlap and gold-to-silver reconciliation.
