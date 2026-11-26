"""
Q2. How sensitive are small payments to network fees?

Unit: hour. Outcome: wallet-to-wallet transfers under $1K. Driver: estimated USD cost of an ERC-20
transfer that hour (base fee x 65k gas x ETH/USD, with ETH/USD derived on-chain).

Identification problem: fees rise *because* demand rises (simultaneity), which biases a naive
regression toward zero or even positive. Mitigations used here:
  1. hour-of-day, day-of-week and month fixed effects (remove predictable demand cycles)
  2. log of large-ticket ($10K+) transfers as a demand control: large tickets face the same
     demand shocks but a fee is a tiny share of their value
  3. the headline is the *relative* elasticity (small minus large) from a stacked model, which
     differences out shocks common to both groups
  4. Newey-West (HAC) standard errors, since hourly errors are autocorrelated

Run: python -m analysis.q2_fee_elasticity
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analysis import stats_utils as su
from analysis.common import FIGURES, SERIES, connect, df_to_md, write_report


def load_panel(con) -> pd.DataFrame:
    p = con.sql("""
        select hour_ts, hour_of_day, day_of_week, protocol_era, est_transfer_fee_usd as fee_usd,
               avg_base_fee_gwei, eth_usd, network_tx_count,
               p2p_small_transfers, p2p_large_transfers, p2p_micro_transfers, p2p_transfers
        from marts.mart_fee_hourly_panel
        where eth_usd is not null and est_transfer_fee_usd > 0 and p2p_transfers > 0
        order by hour_ts
    """).df()
    p["log_fee"] = np.log(p.fee_usd)
    p["log_small"] = np.log1p(p.p2p_small_transfers)
    p["log_large"] = np.log1p(p.p2p_large_transfers)
    p["log_network"] = np.log(p.network_tx_count)
    p["small_share"] = p.p2p_small_transfers / p.p2p_transfers
    p["month"] = p.hour_ts.dt.strftime("%Y-%m")
    p["t"] = (p.hour_ts - p.hour_ts.min()).dt.total_seconds() / 86400 / 365
    return p


def main() -> dict:
    con = connect()
    p = load_panel(con)
    fe = "C(hour_of_day) + C(day_of_week) + C(month)"
    hac = {"cov_type": "HAC", "cov_kwds": {"maxlags": 24}}

    naive = smf.ols("log_small ~ log_fee", data=p).fit(**hac)
    m1 = smf.ols(f"log_small ~ log_fee + {fe}", data=p).fit(**hac)
    m2 = smf.ols(f"log_small ~ log_fee + log_large + log_network + {fe}", data=p).fit(**hac)

    # Stacked model: small vs large in one regression, fee effect allowed to differ by group
    st = pd.concat([
        p.assign(group="small", log_n=p.log_small),
        p.assign(group="large", log_n=p.log_large),
    ])
    st["is_small"] = (st.group == "small").astype(int)
    m3 = smf.ols(f"log_n ~ log_fee * is_small + is_small:({fe}) + {fe}", data=st).fit(**hac)
    rel, rel_ci = m3.params["log_fee:is_small"], m3.conf_int().loc["log_fee:is_small"].values

    corr_p = su.correlation_with_ci(p.log_fee, p.small_share, "pearson")
    corr_s = su.correlation_with_ci(p.fee_usd, p.small_share, "spearman")

    # Binned view: small-ticket share of P2P by fee decile (descriptive, no controls)
    p["fee_decile"] = pd.qcut(p.fee_usd, 10, labels=False) + 1
    bins = (p.groupby("fee_decile")
            .agg(fee_from=("fee_usd", "min"), fee_to=("fee_usd", "max"), hours=("fee_usd", "size"),
                 small_share=("small_share", "mean"), small_per_hour=("p2p_small_transfers", "mean"),
                 large_per_hour=("p2p_large_transfers", "mean"))
            .reset_index())

    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.plot(bins.fee_to, bins.small_share * 100, marker="o", color=SERIES[0], ms=7)
    ax.set_xscale("log")
    ax.set_xlabel("Cost of one stablecoin transfer, USD (upper edge of fee decile, log scale)")
    ax.set_ylabel("Under-$1K share of P2P, %")
    ax.set_title("Small payments thin out as fees rise")
    fig.savefig(FIGURES / "q2_fee_deciles.png")
    plt.close(fig)

    def row(name, m, term="log_fee"):
        lo, hi = m.conf_int().loc[term]
        return {"model": name, "elasticity": m.params[term], "ci_low": lo, "ci_high": hi,
                "p_value": m.pvalues[term], "r2": m.rsquared, "n_hours": int(m.nobs)}

    table = pd.DataFrame([
        row("1. Naive (no controls)", naive),
        row("2. + hour, weekday, month fixed effects", m1),
        row("3. + large-ticket and network demand controls", m2),
    ])

    md = f"""# Q2. Fee sensitivity of small payments

{len(p):,} hours, {p.hour_ts.min():%Y-%m-%d} to {p.hour_ts.max():%Y-%m-%d}. Median transfer cost ${p.fee_usd.median():.2f}
(p10 ${p.fee_usd.quantile(.1):.2f}, p90 ${p.fee_usd.quantile(.9):.2f}).

![deciles](figures/q2_fee_deciles.png)

## Fee deciles (descriptive)
{df_to_md(bins)}

## Elasticity of under-$1K P2P transfers with respect to fee (log-log, Newey-West SE)
{df_to_md(table)}

The naive model is contaminated by simultaneity (busy hours have both more transfers and higher fees).
Adding fixed effects and demand controls moves the estimate to **{m2.params['log_fee']:+.3f}**: a 10% higher fee goes with
about {abs(m2.params['log_fee'])*10:.1f}% {'fewer' if m2.params['log_fee'] < 0 else 'more'} small transfers in that hour, holding demand fixed.

## Relative elasticity (stacked small vs large model)
Small-ticket elasticity minus large-ticket elasticity: **{rel:+.3f}** (95% CI {rel_ci[0]:+.3f} to {rel_ci[1]:+.3f}),
p = {m3.pvalues['log_fee:is_small']:.2g}. Shocks that hit both groups cancel out here, so this is the most
credible number: {'small payments are clearly more fee-sensitive than large ones.' if rel < 0 and rel_ci[1] < 0 else 'no reliable difference between small and large tickets.'}

## Correlation (no controls)
* Pearson r(log fee, small-ticket share) = {corr_p['r']:+.3f} (95% CI {corr_p['ci_low']:+.3f} to {corr_p['ci_high']:+.3f})
* Spearman rho(fee, small-ticket share) = {corr_s['r']:+.3f} (95% CI {corr_s['ci_low']:+.3f} to {corr_s['ci_high']:+.3f})

Correlation is shown for context only. It mixes fee effects with time trends, which the regression controls for.
"""
    write_report("q2_fee_elasticity.md", md)
    return {"elasticity": float(m2.params["log_fee"]), "elasticity_ci": m2.conf_int().loc["log_fee"].tolist(),
            "relative_elasticity": float(rel), "relative_ci": rel_ci.tolist(),
            "median_fee": float(p.fee_usd.median()), "bins": bins}


if __name__ == "__main__":
    main()
