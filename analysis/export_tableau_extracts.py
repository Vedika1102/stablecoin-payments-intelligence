"""Export the dashboard data sources as CSVs for Tableau Public (which cannot connect to Redshift).
In a company setup Tableau Server/Cloud connects live to Redshift `marts` instead; the CSVs have
exactly the same columns as those tables, so the workbook switches with a data-source swap."""

from __future__ import annotations

from analysis.common import ROOT, connect

OUT = ROOT / "tableau" / "extracts"
TABLES = {
    "payment_mix_daily": "select * from marts.mart_payment_mix_daily",
    "fee_hourly_panel": "select * from marts.mart_fee_hourly_panel",
    "activation_funnel": "select * from marts.mart_wallet_activation_funnel",
    "cohort_retention": "select * from marts.mart_wallet_cohort_retention where months_since_start <= 12",
    "segment_mix_monthly": "select * from marts.mart_segment_mix_monthly",
    "dq_summary": "select * from marts.mart_dq_summary",
    "network_daily": """select activity_date, protocol_era, avg(avg_base_fee_gwei) as avg_base_fee_gwei,
                               avg(eth_usd) as eth_usd, avg(est_transfer_fee_usd) as est_transfer_fee_usd,
                               sum(network_tx_count) as network_tx_count
                        from core.fct_network_hourly group by 1, 2 order by 1""",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect()
    for name, sql in TABLES.items():
        df = con.sql(sql).df()
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:<22} {len(df):>8,} rows")


if __name__ == "__main__":
    main()
