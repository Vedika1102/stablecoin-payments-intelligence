"""
Q4 + Q5. Wallet lifecycle: activation and retention of new stablecoin wallets, and USDC vs USDT.

New wallet: first stablecoin activity on or after 2024-01-01 (6 months of lookback in the window),
entering by *receiving* funds (the payout scenario). Funnel:
    receive -> send within 7 days (activation) -> active in month 1 -> active in month 3 (retention)

Tests:
  * chi-squared: does 7-day activation differ by first-receipt size?
  * two-proportion z-tests with CIs: USDC vs USDT activation and month-3 retention
  * logistic regression: month-3 retention on token, first-receipt size, early activation, cohort
  * Kaplan-Meier survival of wallets + log-rank test, USDC vs USDT

Run: python -m analysis.q4_wallet_lifecycle
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analysis import stats_utils as su
from analysis.common import FIGURES, SERIES, connect, df_to_md, pct, pp, write_report

SAMPLE_WALLETS = 400_000   # wallet-level models run on a random sample; aggregates use everything


def main() -> dict:
    con = connect()
    funnel = con.sql("""
        select cohort_month, sum(new_wallets) as new_wallets, sum(sent_within_7d) as sent_7d,
               sum(sent_within_30d) as sent_30d, sum(active_month_1) as active_m1,
               sum(case when month_3_observed then active_month_3 end) as active_m3,
               sum(case when month_3_observed then new_wallets end) as m3_base
        from marts.mart_wallet_activation_funnel group by 1 order by 1
    """).df()
    tot = funnel[["new_wallets", "sent_7d", "sent_30d", "active_m1", "active_m3", "m3_base"]].sum()

    by_band = con.sql("""
        select first_receive_band, sum(new_wallets) as new_wallets, sum(sent_within_7d) as sent_7d
        from marts.mart_wallet_activation_funnel group by 1 order by 1
    """).df()
    by_band["activation_7d"] = by_band.sent_7d / by_band.new_wallets
    chi_band = su.chi_square_independence(np.column_stack([by_band.sent_7d, by_band.new_wallets - by_band.sent_7d]))

    tok = con.sql("""
        select primary_token, sum(new_wallets) as n, sum(sent_within_7d) as sent_7d,
               sum(case when month_3_observed then active_month_3 end) as m3,
               sum(case when month_3_observed then new_wallets end) as m3_base
        from marts.mart_wallet_activation_funnel group by 1
    """).df().set_index("primary_token")
    act_t = su.two_proportion_test(int(tok.loc["USDC", "sent_7d"]), int(tok.loc["USDC", "n"]),
                                   int(tok.loc["USDT", "sent_7d"]), int(tok.loc["USDT", "n"]))
    ret_t = su.two_proportion_test(int(tok.loc["USDC", "m3"]), int(tok.loc["USDC", "m3_base"]),
                                   int(tok.loc["USDT", "m3"]), int(tok.loc["USDT", "m3_base"]))

    # ---------- wallet-level sample for regression + survival ----------
    w = con.sql(f"""
        with p as (
            select wallet, primary_token, first_receive_date, first_send_date, first_receive_usd, last_active_date,
                   case when lifetime_sent_usd >= 0.95 * lifetime_recv_usd and active_days <= 3 then 1 else 0 end
                       as pass_through,
                   date_trunc('month', first_receive_date) as cohort_month
            from staging.stg_wallet_profile
            where first_receive_date >= date '2024-01-01' and first_seen_date = first_receive_date
              and first_receive_date <= date '2025-03-31'          -- month 3 observable
            using sample reservoir({SAMPLE_WALLETS} rows) repeatable (42)
        ),
        m3 as (
            select p.wallet, max(case when date_diff('month', p.cohort_month, m.activity_month) = 3 then 1 else 0 end) as active_m3
            from p join staging.stg_wallet_monthly m on m.wallet = p.wallet group by 1
        )
        select p.*, coalesce(m3.active_m3, 0) as active_m3,
               case when p.first_send_date is not null and date_diff('day', p.first_receive_date, p.first_send_date) <= 7
                    then 1 else 0 end as sent_7d
        from p left join m3 using (wallet)
    """).df()
    w["band"] = pd.cut(w.first_receive_usd, [-1, 100, 1_000, 10_000, np.inf],
                       labels=["under_100", "100_1K", "1K_10K", "10K_plus"]).astype(str)
    w["cohort"] = pd.to_datetime(w.cohort_month).dt.strftime("%Y-%m")
    logit = smf.logit("active_m3 ~ C(primary_token, Treatment('USDT')) + C(band, Treatment('under_100')) + sent_7d + pass_through + C(cohort)",
                      data=w).fit(disp=0, maxiter=100)
    base = smf.logit("active_m3 ~ C(primary_token, Treatment('USDT')) + C(band, Treatment('under_100')) + sent_7d + C(cohort)",
                     data=w).fit(disp=0, maxiter=100)
    or_sent_base = float(np.exp(base.params["sent_7d"]))
    ors = pd.DataFrame({"odds_ratio": np.exp(logit.params), "ci_low": np.exp(logit.conf_int()[0]),
                        "ci_high": np.exp(logit.conf_int()[1]), "p_value": logit.pvalues})
    ors = ors[~ors.index.str.contains("cohort|Intercept")].reset_index().rename(columns={"index": "term"})
    from sklearn.metrics import roc_auc_score
    auc = roc_auc_score(w.active_m3, logit.predict(w))

    # Pass-through wallets: forward (almost) everything they receive within a few active days.
    # Typical of exchange deposit addresses and one-shot forwarding wallets, not of people holding a balance.
    pt = con.sql("""
        with p as (
            select *, case when lifetime_sent_usd >= 0.95 * lifetime_recv_usd and active_days <= 3 then 1 else 0 end
                          as pass_through,
                      case when first_send_date is not null and first_send_date <= first_receive_date + 7
                           then 1 else 0 end as sent_7d
            from staging.stg_wallet_profile
            where first_receive_date >= date '2024-01-01' and first_seen_date = first_receive_date
              and first_receive_date <= date '2025-03-31'
        )
        select case when sent_7d = 1 then 'yes' else 'no' end as sent_within_7d,
               case when pass_through = 1 then 'pass-through' else 'holds a balance' end as wallet_type,
               count(*) as wallets,
               avg(case when last_active_date >= first_receive_date + 60 then 1.0 else 0 end) as active_after_60d
        from p group by 1, 2 order by 1 desc, 2
    """).df()
    pt["share_of_new_wallets"] = pt.wallets / pt.wallets.sum()
    pt_share_of_activated = (pt[(pt.sent_within_7d == "yes") & (pt.wallet_type == "pass-through")].wallets.sum()
                             / pt[pt.sent_within_7d == "yes"].wallets.sum())
    ret = pt.set_index(["sent_within_7d", "wallet_type"]).active_after_60d

    # Survival: months from first receipt to last activity; censored if active in the last 60 days
    end = pd.Timestamp("2025-06-30")
    w["dur_m"] = ((pd.to_datetime(w.last_active_date) - pd.to_datetime(w.first_receive_date)).dt.days / 30.44).round().astype(int)
    w["churned"] = (pd.to_datetime(w.last_active_date) < end - pd.Timedelta(days=60)).astype(int)
    km = {t: su.kaplan_meier(g.dur_m.values, g.churned.values) for t, g in w.groupby("primary_token")}
    lr = su.logrank_test(w[w.primary_token == "USDC"].dur_m, w[w.primary_token == "USDC"].churned,
                         w[w.primary_token == "USDT"].dur_m, w[w.primary_token == "USDT"].churned)

    # ---------- figures ----------
    fig, ax = plt.subplots(figsize=(7, 3.4))
    steps = ["New wallets", "Sent in 7 days", "Sent in 30 days", "Active month 1", "Active month 3"]
    vals = [1, tot.sent_7d / tot.new_wallets, tot.sent_30d / tot.new_wallets, tot.active_m1 / tot.new_wallets,
            tot.active_m3 / tot.m3_base]
    ax.barh(steps[::-1], [v * 100 for v in vals[::-1]], color=SERIES[0], height=0.6)
    for i, v in enumerate(vals[::-1]):
        ax.text(v * 100 + 1, i, f"{v*100:.1f}%", va="center", fontsize=9)
    ax.set_xlim(0, 110)
    ax.set_xlabel("% of new wallets")
    ax.set_title("New-wallet activation funnel (2024-01 onward cohorts)")
    ax.grid(axis="y", visible=False)
    fig.savefig(FIGURES / "q4_activation_funnel.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.4))
    for i, (t, k) in enumerate(km.items()):
        ax.step(np.concatenate([[0], k["time"]]), np.concatenate([[1], k["survival"]]) * 100, where="post",
                color=SERIES[i], label=t)
    ax.set_xlim(0, 15)
    ax.set_xlabel("Months since first receipt")
    ax.set_ylabel("% of wallets still active")
    ax.set_title("Wallet survival by primary stablecoin (Kaplan-Meier)")
    ax.legend()
    fig.savefig(FIGURES / "q4_survival_usdc_usdt.png")
    plt.close(fig)

    md = f"""# Q4. New-wallet activation and retention

{int(tot.new_wallets):,} new wallets that entered by receiving a stablecoin, cohorts {funnel.cohort_month.min():%b %Y} to
{funnel.cohort_month.max():%b %Y}.

![funnel](figures/q4_activation_funnel.png)

| Step | Wallets | Rate |
|---|---|---|
| Received first stablecoin | {int(tot.new_wallets):,} | 100% |
| Sent within 7 days (activation) | {int(tot.sent_7d):,} | {pct(tot.sent_7d / tot.new_wallets)} |
| Sent within 30 days | {int(tot.sent_30d):,} | {pct(tot.sent_30d / tot.new_wallets)} |
| Active in month 1 | {int(tot.active_m1):,} | {pct(tot.active_m1 / tot.new_wallets)} |
| Active in month 3 (cohorts with 3 months observed) | {int(tot.active_m3):,} | {pct(tot.active_m3 / tot.m3_base)} |

## Activation by size of first receipt
{df_to_md(by_band)}

Chi-squared test of independence: chi-squared = {chi_band['chi2']:,.0f}, df = {chi_band['dof']}, p < 0.001,
Cramer's V = {chi_band['cramers_v']:.3f}.

# Q5. USDC vs USDT

| Metric | USDC | USDT | USDT - USDC | 95% CI | p |
|---|---|---|---|---|---|
| 7-day activation | {pct(act_t['control_rate'])} | {pct(act_t['treatment_rate'])} | {pp(act_t['abs_diff'])} | {pp(act_t['ci_low'])} to {pp(act_t['ci_high'])} | {su.fmt_p(act_t['p_value'])} |
| Month-3 retention | {pct(ret_t['control_rate'])} | {pct(ret_t['treatment_rate'])} | {pp(ret_t['abs_diff'])} | {pp(ret_t['ci_low'])} to {pp(ret_t['ci_high'])} | {su.fmt_p(ret_t['p_value'])} |

![survival](figures/q4_survival_usdc_usdt.png)

Log-rank test (survival curves equal?): chi-squared = {lr['chi2']:,.1f}, p = {su.fmt_p(lr['p_value'])}
(on a random sample of {len(w):,} wallets).

## What predicts month-3 retention? (logistic regression, {len(w):,}-wallet sample, cohort fixed effects)
{df_to_md(ors)}

AUC = {auc:.3f}.

## The activation metric is mostly pass-through traffic
The naive reading of the funnel is "{pct(tot.sent_7d / tot.new_wallets)} of new wallets activate". But in a model
*without* the pass-through flag, a week-one send goes with an odds ratio of **{or_sent_base:.2f}** for month-3 retention:
activation looks like it predicts churn. Add a flag for pass-through wallets (send at least 95% of what they received,
at most 3 active days) and the sign flips: activation's odds ratio becomes
**{ors.set_index('term').loc['sent_7d', 'odds_ratio']:.2f}**, and pass-through itself is
{ors.set_index('term').loc['pass_through', 'odds_ratio']:.2f}. A classic confounder: the two kinds of wallet were
pooled in one metric. On the full population (cohorts Jan 2024 to Mar 2025):

{df_to_md(pt)}

{pct(pt_share_of_activated)} of "activated" wallets are pass-through, and only {pct(ret[('yes', 'pass-through')])} of them are
still active 60+ days after their first receipt, against {pct(ret[('yes', 'holds a balance')])} for activated wallets that
keep a balance. These are typically exchange deposit addresses and one-shot forwarding wallets. **Recommendation:**
define activation as "sent within 7 days *and* kept a balance", and report pass-through wallets separately.
Otherwise the KPI rewards churn.
"""
    write_report("q4_wallet_lifecycle.md", md)
    return {"pass_through_share_of_activated": float(pt_share_of_activated),
            "ret60_activated_pass_through": float(ret[('yes', 'pass-through')]),
            "ret60_activated_holder": float(ret[('yes', 'holds a balance')]),
            "new_wallets": int(tot.new_wallets), "activation_7d": tot.sent_7d / tot.new_wallets,
            "retention_m3": tot.active_m3 / tot.m3_base, "act_usdc": act_t["control_rate"], "act_usdt": act_t["treatment_rate"],
            "ret_usdc": ret_t["control_rate"], "ret_usdt": ret_t["treatment_rate"],
            "or_sent7d": float(ors.set_index("term").loc["sent_7d", "odds_ratio"]),
            "or_sent7d_without_pass_through": or_sent_base,
            "or_pass_through": float(ors.set_index("term").loc["pass_through", "odds_ratio"]), "auc": auc, "by_band": by_band}


if __name__ == "__main__":
    main()
