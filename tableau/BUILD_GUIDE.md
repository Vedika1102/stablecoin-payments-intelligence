# Tableau Public build guide: "Stablecoin Payments Intelligence"

This guide gets you from the CSVs in `tableau/extracts/` to a published Tableau Public workbook
in about 2 to 3 hours. Tableau Public is free (Tableau Public desktop app plus a public profile).
In a company setup the same workbook connects live to the Redshift `marts` schema; the CSVs have
identical columns, so it's a data source swap.

## 0. Setup
1. Install **Tableau Public** (desktop) and sign in.
2. *Connect → Text file →* open each CSV in `tableau/extracts/`. Add them as **separate data
   sources** (don't join them; each is already at its own grain):

| Data source | Grain | Used on |
|---|---|---|
| `payment_mix_daily.csv` | day x token x flow category | Overview, Payment mix |
| `network_daily.csv` | day | Overview, Fees |
| `fee_hourly_panel.csv` | hour | Fees, Dencun |
| `activation_funnel.csv` | cohort month x token x first-receipt band | Lifecycle |
| `cohort_retention.csv` | cohort month x token x months since start | Lifecycle |
| `segment_mix_monthly.csv` | month x segment | Payment mix |
| `dq_summary.csv` | check x partition | Data quality |

3. Set date fields to *Date* type (`activity_date`, `activity_month`, `cohort_month`) and `hour_ts`
   to *Date & Time*.

## 1. Calculated fields

```text
// payment_mix_daily
[P2P small transfers]   = SUM(IF [flow_category] = "p2p_small_ticket" THEN [transfers] END)
[Payment-like share]    = [P2P small transfers] / SUM([transfers])
[Volume $B]             = SUM([volume_usd]) / 1e9
[Flow label]            = CASE [flow_category]
                            WHEN "p2p_small_ticket" THEN "P2P under $1K"
                            WHEN "p2p_large_ticket" THEN "P2P $1K+"
                            WHEN "contract_flow"    THEN "Contract flows"
                            WHEN "dust_spam"        THEN "Dust / spam"
                            ELSE "Mint / burn" END

// fee_hourly_panel
[Small share of P2P]    = SUM([p2p_small_transfers]) / SUM([p2p_transfers])
[Fee decile]            = (create a Bin on est_transfer_fee_usd, or use the deciles table in reports/q2)
[Post Dencun]           = [hour_ts] >= #2024-03-13#
[Small index]           = SUM([p2p_small_transfers]) /
                          WINDOW_AVG(SUM(IF [hour_ts] < #2024-03-13# THEN [p2p_small_transfers] END))   // indexed to pre-period = 1
[Large index]           = same with p2p_large_transfers

// activation_funnel
[Activation 7d]         = SUM([sent_within_7d]) / SUM([new_wallets])
[Retention M3]          = SUM(IF [month_3_observed] THEN [active_month_3] END)
                          / SUM(IF [month_3_observed] THEN [new_wallets] END)

// cohort_retention
[Retention]             = SUM([active_wallets]) / SUM([cohort_size])

// dq_summary
[Status]                = IF [passed] THEN "Pass" ELSEIF [severity] = "warn" THEN "Warn" ELSE "Fail" END
```

## 2. Dashboards (1200 x 800, one story per dashboard)

**D1. Executive overview**
* KPI tiles (big number + small sparkline): total transfers, volume ($B), payment-like share, median
  transfer fee ($), new wallets, 7-day activation, month-3 retention.
* Line: monthly payment-like share with protocol era bands (reference band for 2024-03-13 onward,
  label it "Dencun").
* One-sentence takeaway text box per tile, copied from the memo.

**D2. What stablecoins are used for**
* 100% stacked area: share of transfers by `Flow label` per month. Filter: token.
* Bar: share of transfers vs share of volume by flow category (side by side). This shows the
  "most transfers are small, most value is large" story.
* Bar: wallet-months by segment, colored by segment, with a tooltip showing volume.

**D3. Fees and small payments**
* Line: daily median transfer fee ($) with era bands.
* Scatter: hourly small share of P2P (y) vs `est_transfer_fee_usd` (x, log scale), with a
  trend line (Analytics pane → Trend line → logarithmic). Tooltip shows the hour.
* Text: the elasticity and relative elasticity with CIs from `reports/q2_fee_elasticity.md`.

**D4. Natural experiment: Dencun**
* Dual lines on a **single axis**: `Small index` and `Large index` by day, ±13 weeks around
  2024-03-13, with a vertical reference line on the date.
* Image object: `reports/figures/q3_dencun_event_study.png` (the event study), plus the DiD
  estimate and placebo result as text.

**D5. Wallet lifecycle**
* Funnel bars: new → sent in 7d → sent in 30d → active M1 → active M3.
* Cohort heatmap: rows = `cohort_month`, columns = `months_since_start` (0 to 12), color =
  `Retention` (single-hue sequential), label = percentage.
* USDC vs USDT: bar pair for activation and M3 retention with CI error bars (type the CI values
  from `reports/q4_wallet_lifecycle.md` into a small table or annotate).
* Filters: primary token, first-receipt band.

**D6. Data quality**
* Table: dataset, check, status (icon + color: pass green, warn amber, fail red, with the word
  too), observed, threshold, partition. This shows reviewers the pipeline is trustworthy.

## 3. Style rules
* One color per flow category, kept the same on every dashboard. Suggested order: P2P under $1K
  `#257de0`, P2P $1K+ `#f47230`, contract flows `#00b894`, mint/burn `#f2a600`, dust/spam `#e87ba4`.
  Exclude `dust_spam` from every payment KPI (filter it out on D1 and D3).
* No dual axes. Index series to a common base instead (D4).
* Every chart title states the takeaway ("Small payments thin out as fees rise"), not just the
  metric name.
* Add a footer to every dashboard: "Source: AWS Public Blockchain Data (Ethereum), processed
  with PySpark on AWS Glue. Window Jul 2023 to Jun 2025."

## 4. Publish
*File → Save to Tableau Public*. Then on your profile, set the workbook to show sheets as tabs,
add a description that links the GitHub repo, and pin the workbook.
