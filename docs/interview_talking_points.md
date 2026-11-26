# Interview talking points

Short answers to the questions a BIE loop is likely to ask about this project. Each one ties a
design choice to a reason and a trade-off. Numbers come from `reports/`.

## "Walk me through the project in two minutes"
* **Problem:** stablecoins move trillions of dollars a year, but how much of that is actual
  payments (people and businesses paying each other) versus trading and treasury moves? And do
  network fees decide whether small payments happen at all?
* **Data:** the AWS Public Blockchain dataset (Ethereum), read in place from S3. Every USDC, USDT,
  DAI and PYUSD transfer for two years (Jul 2023 to Jun 2025), plus every block for fees and the
  Uniswap pool for an on-chain ETH/USD price. See `reports/pipeline_run.md` for row counts.
* **Pipeline:** PySpark medallion lake (bronze, silver, gold) built to run on Glue, with a DQ
  framework on every layer, orchestrated by Step Functions (or MWAA), provisioned with Terraform,
  shipped with GitHub Actions.
* **Warehouse:** Redshift Serverless star schema (SCD2 wallet dimension, wallet and network facts),
  modelled and tested in dbt.
* **Analysis:** fee elasticity regression, a difference-in-differences on the Dencun upgrade (a
  real fee shock), and a wallet lifecycle study (funnel, cohorts, logistic regression, survival).
* **Output:** a Tableau Public dashboard and a one-page memo with recommendations.

## Data engineering

**Why read the public bucket in place instead of copying it?**
Column pruning plus explicit date-partition paths mean a month reads about 4 GB instead of tens.
Copying 10+ TB would cost money and add a sync job. The risk is schema drift in a bucket I don't
own, so bronze runs DQ checks (non-null keys, hash format, address padding, FK to blocks) and fails
loudly.

**What's in each layer and why?**
Bronze is a faithful, filtered copy (raw padded addresses, raw integer amounts) so I can always
replay. Silver is where the business logic lives (dedupe on tx hash + log index, address
normalization, decimals, fees, contract flags), and it's unit tested. Gold is aggregates at the
grains the warehouse needs.

**How do you make backfills safe?**
Dynamic partition overwrite on every table. Re-running any day or month replaces exactly those
partitions, so jobs are idempotent. Glue `max_concurrent_runs = 1` keeps one writer per table.

**Biggest data quality catch?**
Address-poisoning spam. In July 2023, about 515k of 575k "under $10" wallet-to-wallet transfers
were zero-value fakes that scammers emit from look-alike addresses. Left in, they'd have made
"small payments" look 10x bigger than they are. I found it by profiling the smallest ticket
bucket, then added a `dust_spam` category and excluded it from all wallet and payment metrics.
That's the kind of thing a dashboard would happily chart without anyone noticing.

**How do you know gold is right?**
Reconciliation checks: gold daily KPIs must match silver row counts and volume exactly, and
wallet-level sends must equal the EOA sends in silver. dbt singular tests repeat that in the
warehouse for a sample day. All results land in `_dq_results` and feed a DQ dashboard.

**Why no price API?**
ETH/USD comes from the hourly median of Uniswap v3 USDC/WETH swaps, so the whole project
reproduces from one dataset with no API keys or licences. A plausibility check guards it.

## Warehouse and modelling

**Why SCD2 on wallets?**
A wallet's behaviour segment changes month to month. If a payout wallet becomes a high-volume
service later, a Type 1 dimension would rewrite history and inflate past metrics for that
segment. SCD2 lets reports use the segment the wallet had at the time. Built with
gaps-and-islands so consecutive months with the same segment collapse into one version.

**Distribution and sort keys?**
`DISTKEY(wallet)` on dim_wallet and the wallet facts, because cohort building and SCD2 as-of joins
are wallet-keyed and co-locate with no redistribution. Small dimensions are `DISTSTYLE ALL`.
Sort keys on date for range-restricted scans. Risk: whale wallets skew slices, checked in
`svv_table_info.skew_rows`.

**Spectrum or COPY?**
Both. Aggregates (gold) are COPY'd into managed storage because dashboards hit them constantly.
Transfer-level detail stays in S3 behind a Spectrum external schema for occasional drill-downs,
where paying per TB scanned beats storing hundreds of millions of rows.

**Why dbt on DuckDB in CI?**
The same models and tests run on every PR against real data without a Redshift cluster. Prod
targets Redshift. Dialect differences are handled in macros.

## Statistics

**Fee elasticity: isn't fee endogenous?**
Yes. Busy hours have high fees *and* high demand, so a naive regression of volume on fee is biased
toward zero or even positive. Two defenses: (1) model the *share* of small P2P transfers among all
P2P transfers, which nets out overall demand, and (2) add hour-of-week and month fixed effects
plus HAC standard errors. The cleanest answer is the natural experiment below.

**Dencun difference-in-differences.**
EIP-4844 (2024-03-13) cut L2 data costs. It changed the L1 fee environment on a known date for
reasons unrelated to stablecoin demand. Treated group: small tickets (under $1K, most
fee-sensitive). Control: large tickets ($10K+, where a few dollars of fee doesn't matter). I
check parallel pre-trends with an event study and run a placebo on 2023-12-13, which should show
nothing. Caveat: Dencun also pulled users to L2s, so the L1 effect is a net of two forces, and I
say that in the memo.

**Why report effect sizes?**
With hundreds of millions of rows every p-value is tiny. Cohen's h, Cramér's V, odds ratios and
elasticities with confidence intervals are what drive decisions.

**Most interesting finding?**
The activation metric. 71% of new wallets "activate" (send within 7 days), which looks great. But 80% of
those are pass-through wallets that forward everything within 3 active days (exchange deposit addresses,
forwarding wallets), and only 5% of them are active 60 days later, against 60% for activated wallets
that keep a balance. Without a pass-through flag, the logistic model says activation *predicts churn*
(odds ratio 0.55). With the flag the sign flips (1.51). Classic confounding from pooling two populations,
and a KPI that would reward the wrong behaviour.

**What happened with the Dencun DiD?**
It didn't hold up: main effect p = 0.09, pre-period event-study coefficients drift up to 0.56 log points,
and a placebo date shows a similar effect. Early March 2024 was a market surge that moved large tickets,
so small and large weren't on parallel paths. I report it as inconclusive and lean on the fee elasticity
instead. Knowing when not to claim causality is part of the job.

**What broke while building it?**
The local disk filled up during the backfill. Root causes: cached 78M-row registry spilling to disk and
Spark shuffle files that weren't cleaned between months. Fixes: semi-join + broadcast for the registry,
one Spark app per month for silver, month-by-month gold. Same patterns you'd use to cut Glue DPU cost.

**Lifecycle: conditioning bias?**
New wallets are defined as first activity on or after 2024-01-01, with six months of lookback to
screen out quiet old wallets. Month-3 retention only counts cohorts whose month 3 is observed
(right-censoring). Kaplan-Meier handles censoring for survival.

## Cost and operations
* Full two-year backfill on Glue: about 10 G.1X workers for ~2 hours, roughly $9.
* Athena workgroup has a per-query scan cutoff; Redshift Serverless has a usage limit.
* Step Functions retries the ingest every 30 minutes for up to 3 hours when the public bucket
  hasn't landed yesterday's partition yet (`SourceNotReady`), then alerts via SNS.
* CloudWatch alarms on job failure and DQ failures.

## What I'd do next
* Add L2s (Base, Arbitrum) where small payments moved after Dencun. The public dataset doesn't
  cover them, so it'd need another source.
* Label known exchange and payment-processor wallets to sharpen the segments.
* Stream with Kinesis for intraday monitoring of de-peg events.
