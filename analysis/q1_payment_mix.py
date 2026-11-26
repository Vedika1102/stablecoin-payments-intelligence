"""
Q1. How much Ethereum stablecoin activity looks like payments?

Flow categories (from the warehouse):
  p2p_small_ticket  wallet-to-wallet (both sides externally owned accounts), under $1K
  p2p_large_ticket  wallet-to-wallet, $1K and up
  contract_flow     at least one side is a contract (DEX pools, exchange contracts, bridges, smart wallets)
  mint_burn         issuance and redemption by the issuer

Run: python -m analysis.q1_payment_mix
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from analysis import stats_utils as su
from analysis.common import FIGURES, SERIES, connect, df_to_md, pct, write_report

CATS = ["p2p_small_ticket", "p2p_large_ticket", "contract_flow", "mint_burn", "dust_spam"]
CAT_LABEL = {"p2p_small_ticket": "P2P under $1K", "p2p_large_ticket": "P2P $1K+",
             "contract_flow": "Contract flows", "mint_burn": "Mint / burn",
             "dust_spam": "Dust / spam (< 1 cent)"}


def main() -> dict:
    con = connect()
    m = con.sql("""
        select date_trunc('month', activity_date) as month, flow_category,
               sum(transfers) as transfers, sum(volume_usd) as volume_usd
        from marts.mart_payment_mix_daily group by 1, 2 order by 1, 2
    """).df()
    piv_n = m.pivot(index="month", columns="flow_category", values="transfers").fillna(0)[CATS]
    share_n = piv_n.div(piv_n.sum(axis=1), axis=0)

    tot = con.sql("""
        select flow_category, sum(transfers) as transfers, sum(volume_usd) as volume_usd
        from marts.mart_payment_mix_daily group by 1
    """).df().set_index("flow_category").loc[CATS]
    tot["share_of_transfers"] = tot.transfers / tot.transfers.sum()
    tot["share_of_volume"] = tot.volume_usd / tot.volume_usd.sum()
    tot["avg_ticket_usd"] = tot.volume_usd / tot.transfers

    by_token = con.sql("""
        select token_symbol,
               sum(case when flow_category = 'p2p_small_ticket' then transfers else 0 end) as p2p_small,
               sum(transfers) as total
        from marts.mart_payment_mix_daily group by 1 order by total desc
    """).df()
    by_token["p2p_small_share"] = by_token.p2p_small / by_token.total
    # Is the payment-like share different between USDC and USDT? (two-proportion z-test)
    u = by_token.set_index("token_symbol")
    tok_test = su.two_proportion_test(int(u.loc["USDC", "p2p_small"]), int(u.loc["USDC", "total"]),
                                      int(u.loc["USDT", "p2p_small"]), int(u.loc["USDT", "total"]))

    seg = con.sql("""
        select segment, sum(wallets) as wallet_months, sum(transfers_sent) as transfers_sent,
               sum(volume_sent_usd) as volume_sent_usd, sum(usdc_primary_wallets) as usdc_primary
        from marts.mart_segment_mix_monthly group by 1 order by wallet_months desc
    """).df()
    seg["share_wallet_months"] = seg.wallet_months / seg.wallet_months.sum()
    seg["share_volume"] = seg.volume_sent_usd / seg.volume_sent_usd.sum()
    seg["usdc_primary_share"] = seg.usdc_primary / seg.wallet_months
    # Segment x primary token: are USDC and USDT users behaviourally different? (chi-squared, Cramer's V)
    tab = np.column_stack([seg.usdc_primary, seg.wallet_months - seg.usdc_primary])
    chi = su.chi_square_independence(tab)

    # ---- figure: monthly mix (share of transfers), stacked area ----
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.stackplot(share_n.index, *[share_n[c] * 100 for c in CATS], labels=[CAT_LABEL[c] for c in CATS],
                 colors=SERIES[:5], alpha=0.95, edgecolor="white", linewidth=0.6)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of stablecoin transfers")
    ax.set_title("What Ethereum stablecoin transfers are used for, by month")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.savefig(FIGURES / "q1_payment_mix.png")
    plt.close(fig)

    first, last = share_n.index.min(), share_n.index.max()
    md = f"""# Q1. How much stablecoin activity looks like payments?

Window: {first:%b %Y} to {last:%b %Y}. {tot.transfers.sum():,.0f} USDC, USDT, DAI and PYUSD transfers, ${tot.volume_usd.sum()/1e12:,.2f} trillion moved.

![mix](figures/q1_payment_mix.png)

## Mix over the full window
{df_to_md(tot.reset_index()[['flow_category', 'transfers', 'share_of_transfers', 'volume_usd', 'share_of_volume', 'avg_ticket_usd']])}

**Read:** person-to-person transfers under $1K are {pct(tot.loc['p2p_small_ticket', 'share_of_transfers'])} of transfers but only
{pct(tot.loc['p2p_small_ticket', 'share_of_volume'], 2)} of value. Value is dominated by contract flows and large
wallet-to-wallet moves (exchanges, market makers, treasury). The share of small P2P transfers moved from
{pct(share_n['p2p_small_ticket'].iloc[0])} in {first:%b %Y} to {pct(share_n['p2p_small_ticket'].iloc[-1])} in {last:%b %Y}.

## USDC vs USDT: who carries the payment-like traffic?
{df_to_md(by_token)}

Small-ticket P2P share, USDT minus USDC: {tok_test['abs_diff']*100:+.2f} pp (95% CI {tok_test['ci_low']*100:+.2f} to {tok_test['ci_high']*100:+.2f}),
z = {tok_test['z']:.1f}. With hundreds of millions of rows almost any gap is "significant", so the effect size (Cohen's h =
{tok_test['cohens_h']:.3f}) is the number to judge.

## Wallet segments (wallet-months)
Each active wallet is re-scored every month by behaviour (rules in `docs/metric_definitions.md`).

{df_to_md(seg[['segment', 'wallet_months', 'share_wallet_months', 'volume_sent_usd', 'share_volume', 'usdc_primary_share']])}

Segment mix differs by primary token: chi-squared = {chi['chi2']:,.0f} (df {chi['dof']}), Cramer's V = {chi['cramers_v']:.3f}.
"""
    write_report("q1_payment_mix.md", md)
    return {"p2p_small_share_transfers": float(tot.loc["p2p_small_ticket", "share_of_transfers"]),
            "p2p_small_share_volume": float(tot.loc["p2p_small_ticket", "share_of_volume"]),
            "total_transfers": float(tot.transfers.sum()), "total_volume": float(tot.volume_usd.sum()),
            "payment_like_wallet_share": float(seg.set_index("segment").loc["payment_like", "share_wallet_months"])
            if "payment_like" in set(seg.segment) else float("nan")}


if __name__ == "__main__":
    main()
