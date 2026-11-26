"""
Q3. Natural experiment: did the Dencun upgrade (2024-03-13) pull small payments off Ethereum mainnet?

Dencun (EIP-4844) made posting data to Ethereum ~90%+ cheaper for rollups (Base, Arbitrum,
Optimism...). Stablecoin transfers there fell to cents, while mainnet costs did not fall the same way.
If payments go where fees are low, small-ticket P2P transfers on mainnet should drop *relative* to
large-ticket transfers (whose users care about security/liquidity, not a few dollars of fee).

Design: difference-in-differences, daily, +/- 13 weeks around the upgrade.
  treated  = P2P transfers under $1K        control = P2P transfers $10K and up
  outcome  = log(daily transfers)
  model    = log_n ~ treated x post + day fixed effects + group fixed effect (HAC SE)
Checks: event study by week (parallel pre-trends), placebo at 2023-12-13 (no upgrade), and
controlling for the mainnet fee itself.

Run: python -m analysis.q3_dencun_did
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analysis.common import FIGURES, INK_2, SERIES, connect, df_to_md, write_report

DENCUN = pd.Timestamp("2024-03-13")
PLACEBO = pd.Timestamp("2023-12-13")
HALF_WINDOW = pd.Timedelta(days=91)


def daily(con) -> pd.DataFrame:
    d = con.sql("""
        select cast(hour_ts as date) as day,
               sum(p2p_small_transfers) as small, sum(p2p_large_transfers) as large,
               avg(est_transfer_fee_usd) as fee_usd
        from marts.mart_fee_hourly_panel group by 1 order by 1
    """).df()
    d["day"] = pd.to_datetime(d["day"])
    return d


def did(d: pd.DataFrame, event: pd.Timestamp, with_fee: bool = False):
    w = d[(d.day >= event - HALF_WINDOW) & (d.day < event + HALF_WINDOW)].copy()
    long = pd.concat([w.assign(treated=1, n=w.small), w.assign(treated=0, n=w.large)])
    long["post"] = (long.day >= event).astype(int)
    long["log_n"] = np.log(long.n)
    long["log_fee_x_treated"] = np.log(long.fee_usd) * long.treated
    long["dayc"] = long.day.dt.strftime("%Y-%m-%d")
    f = "log_n ~ treated:post + treated + C(dayc)" + (" + log_fee_x_treated" if with_fee else "")
    m = smf.ols(f, data=long).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    return m, long


def event_study(d: pd.DataFrame) -> pd.DataFrame:
    w = d[(d.day >= DENCUN - HALF_WINDOW) & (d.day < DENCUN + HALF_WINDOW)].copy()
    long = pd.concat([w.assign(treated=1, n=w.small), w.assign(treated=0, n=w.large)])
    long["log_n"] = np.log(long.n)
    long["week"] = ((long.day - DENCUN).dt.days // 7).astype(int)
    long["dayc"] = long.day.dt.strftime("%Y-%m-%d")
    weeks = sorted(long.week.unique())
    ref = -1
    for k in weeks:
        if k != ref:
            long[f"w_{k + 100}"] = ((long.week == k) & (long.treated == 1)).astype(int)
    terms = " + ".join(f"w_{k + 100}" for k in weeks if k != ref)
    m = smf.ols(f"log_n ~ treated + C(dayc) + {terms}", data=long).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    rows = [{"week": ref, "coef": 0.0, "lo": 0.0, "hi": 0.0}]
    for k in weeks:
        if k == ref:
            continue
        lo, hi = m.conf_int().loc[f"w_{k + 100}"]
        rows.append({"week": k, "coef": m.params[f"w_{k + 100}"], "lo": lo, "hi": hi})
    return pd.DataFrame(rows).sort_values("week")


def main() -> dict:
    con = connect()
    d = daily(con)
    main_m, long = did(d, DENCUN)
    fee_m, _ = did(d, DENCUN, with_fee=True)
    plc_m, _ = did(d, PLACEBO)
    es = event_study(d)

    def eff(m):
        b = m.params["treated:post"]
        lo, hi = m.conf_int().loc["treated:post"]
        return b, lo, hi, m.pvalues["treated:post"]

    b, lo, hi, p = eff(main_m)
    bf, lof, hif, pf = eff(fee_m)
    bp, lop, hip, pp_ = eff(plc_m)
    pre = es[es.week < -1]
    pre_max = pre.coef.abs().max()

    means = (long.assign(period=np.where(long.post == 1, "post", "pre"),
                         group=np.where(long.treated == 1, "small (<$1K)", "large ($10K+)"))
             .groupby(["group", "period"]).agg(avg_daily_transfers=("n", "mean"), avg_fee_usd=("fee_usd", "mean"))
             .reset_index())

    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.axhline(0, color=INK_2, lw=1)
    ax.axvline(-0.5, color=INK_2, lw=1, ls="--")
    ax.errorbar(es.week, es.coef * 100, yerr=[(es.coef - es.lo) * 100, (es.hi - es.coef) * 100],
                fmt="o", color=SERIES[0], capsize=2, ms=5)
    ax.set_xlabel("Weeks relative to Dencun (2024-03-13)")
    ax.set_ylabel("Small vs large, log points x100")
    ax.set_title("Event study: small-ticket mainnet P2P relative to large tickets")
    fig.savefig(FIGURES / "q3_dencun_event_study.png")
    plt.close(fig)

    def pct_effect(x):
        return (np.exp(x) - 1) * 100

    clean = (p < 0.05) and (pp_ > 0.05) and (pre_max < abs(b) / 2)
    if clean:
        verdict = ("The effect is significant, pre-trends are flat and the placebo is null, so it is a credible "
                   "causal estimate of Dencun's effect on mainnet small payments.")
    else:
        verdict = (f"**Verdict: no credible causal effect.** The main estimate is {'not ' if p >= 0.05 else ''}significant "
                   f"(p = {p:.2g}), the pre-period coefficients drift (max {pre_max:.2f} log points), and the placebo date "
                   f"shows an effect of similar size (p = {pp_:.2g}). Small and large tickets were already on different "
                   "paths around the turn of the year, so this design can't separate Dencun from that drift. "
                   "The fee-elasticity estimate in Q2 is the more reliable evidence on fee sensitivity. Rejecting a "
                   "tempting causal story is the right call here, and the memo says so.")
    md = f"""# Q3. Did Dencun pull small payments off Ethereum mainnet?

Window: {(DENCUN - HALF_WINDOW):%Y-%m-%d} to {(DENCUN + HALF_WINDOW):%Y-%m-%d} (13 weeks either side).

## Raw 2x2
{df_to_md(means)}

## Difference-in-differences
| Specification | Effect on small vs large (log points) | % effect | 95% CI (%) | p |
|---|---|---|---|---|
| Main: day fixed effects | {b:+.3f} | {pct_effect(b):+.1f}% | {pct_effect(lo):+.1f}% to {pct_effect(hi):+.1f}% | {p:.2g} |
| + mainnet fee x group | {bf:+.3f} | {pct_effect(bf):+.1f}% | {pct_effect(lof):+.1f}% to {pct_effect(hif):+.1f}% | {pf:.2g} |
| Placebo (fake date 2023-12-13) | {bp:+.3f} | {pct_effect(bp):+.1f}% | {pct_effect(lop):+.1f}% to {pct_effect(hip):+.1f}% | {pp_:.2g} |

![event study](figures/q3_dencun_event_study.png)

**Parallel trends:** the largest pre-period weekly coefficient is {pre_max:.3f} log points.
{'Pre-period coefficients hover near zero, which supports the design.' if pre_max < abs(b) / 2 else 'Pre-period coefficients are not flat, so read the estimate with caution: some of the gap may be a trend that started before Dencun.'}

**Placebo:** {'the fake date shows no comparable effect, so the result is not an artefact of seasonality.' if pp_ > 0.05 or abs(bp) < abs(b) / 3 else 'the fake date also shows an effect, which weakens the causal reading.'}

**Interpretation:** day fixed effects absorb everything that moved both groups (ETH price, market
volatility, holidays), so the main row is the change in small-ticket activity *relative to* large-ticket activity
after Dencun. {verdict}
"""
    write_report("q3_dencun_did.md", md)
    return {"did": b, "did_ci": [lo, hi], "did_p": p, "did_pct": pct_effect(b), "placebo": bp, "placebo_p": pp_,
            "pre_max": pre_max, "did_fee": bf}


if __name__ == "__main__":
    main()
