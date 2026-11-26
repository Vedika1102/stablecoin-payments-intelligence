"""Generate the Tableau workbook (tableau/Stablecoin Payments Intelligence.twbx) from code.

Workbook as code: every data source, calculated field, sheet and dashboard is defined below, so the
workbook is reviewable in a pull request and rebuildable after the extracts change.

    python tableau/build_workbook.py

The .twbx packages the CSVs in tableau/extracts/, so it opens anywhere (Tableau Desktop or Public).
In a company setup the same sheets would point at the Redshift `marts` schema instead.
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
EXTRACTS = HERE / "extracts"
OUT = HERE / "Stablecoin Payments Intelligence.twbx"
TWB_NAME = "Stablecoin Payments Intelligence.twb"
DATA_DIR = "Data/extracts"

FOOTER = ("Source: AWS Public Blockchain Data (Ethereum), every USDC, USDT, DAI and PYUSD transfer, "
          "Jul 2023 to Jun 2025. Processed with PySpark on AWS Glue, modelled in dbt and Redshift. "
          "github.com/Vedika1102/stablecoin-payments-intelligence")

# Colours (kept identical on every dashboard)
FLOW_COLOURS = {"P2P under $1K": "#257de0", "P2P $1K+": "#f47230", "Contract flows": "#00b894",
                "Mint / burn": "#f2a600", "Dust / spam": "#e87ba4"}
TOKEN_COLOURS = {"USDC": "#257de0", "USDT": "#00b894", "DAI": "#f2a600", "PYUSD": "#8e6bd8"}
PCT0, PCT1 = "p0%", "p0.0%"
USD2 = 'c"$"#,##0.00;-"$"#,##0.00'
USD0 = 'c"$"#,##0;-"$"#,##0'

# --------------------------------------------------------------------------------------------
# Data sources: file -> column types (Tableau text-file types)
# --------------------------------------------------------------------------------------------
TYPES = {
    "payment_mix_daily": {"activity_date": "date", "transfers": "real", "volume_usd": "real",
                          "avg_median_fee_usd": "real"},
    "network_daily": {"activity_date": "date", "avg_base_fee_gwei": "real", "eth_usd": "real",
                      "est_transfer_fee_usd": "real", "network_tx_count": "real"},
    "fee_hourly_panel": {"hour_ts": "datetime", "activity_date": "date", "hour_of_day": "integer",
                         "day_of_week": "integer", "avg_base_fee_gwei": "real", "avg_block_utilization": "real",
                         "network_tx_count": "integer", "blocks": "integer", "eth_usd": "real",
                         "oracle_swaps": "integer", "est_transfer_fee_usd": "real", "p2p_small_transfers": "real",
                         "p2p_large_transfers": "real", "p2p_micro_transfers": "real", "p2p_transfers": "real",
                         "p2p_volume_usd": "real"},
    "activation_funnel": {"cohort_month": "date", "new_wallets": "integer", "sent_within_7d": "real",
                          "sent_within_30d": "real", "active_month_1": "real", "active_month_3": "real"},
    "cohort_retention": {"cohort_month": "date", "months_since_start": "integer", "cohort_size": "integer",
                         "active_wallets": "integer", "retention_rate": "real"},
    "segment_mix_monthly": {"activity_month": "date", "wallets": "integer", "transfers_sent": "real",
                            "volume_sent_usd": "real", "small_ticket_sent": "real", "usdc_primary_wallets": "real"},
    "dq_summary": {"observed": "real", "run_ts": "datetime"},
}
CAPTIONS = {
    "payment_mix_daily": "Payment mix (daily)", "network_daily": "Network fees (daily)",
    "fee_hourly_panel": "Fees and payments (hourly)", "activation_funnel": "Activation funnel",
    "cohort_retention": "Cohort retention", "segment_mix_monthly": "Wallet segments (monthly)",
    "dq_summary": "Data quality checks",
}
REMOTE = {"string": "129", "integer": "20", "real": "5", "date": "133", "datetime": "135", "boolean": "11"}


def header(name: str) -> list[str]:
    with open(EXTRACTS / f"{name}.csv", newline="") as f:
        return next(csv.reader(f))


def ds_id(name: str) -> str:
    return f"federated.{name.replace('_', '')}"


# --------------------------------------------------------------------------------------------
# Calculated fields: (datasource, id, caption, formula, datatype, role, format)
# --------------------------------------------------------------------------------------------
P = "[Parameters]"
CALCS = [
    # payment mix
    ("payment_mix_daily", "c_flow_label", "Flow label",
     'CASE [flow_category] WHEN "p2p_small_ticket" THEN "P2P under $1K" WHEN "p2p_large_ticket" THEN "P2P $1K+" '
     'WHEN "contract_flow" THEN "Contract flows" WHEN "dust_spam" THEN "Dust / spam" ELSE "Mint / burn" END',
     "string", "dimension", None),
    ("payment_mix_daily", "c_tx_ex_spam_m", "Transfers (M, ex spam)",
     'SUM(IF [flow_category] != "dust_spam" THEN [transfers] END) / 1000000', "real", "measure", '*#,##0.0"M"'),
    ("payment_mix_daily", "c_vol_t", "Volume ($T, ex spam)",
     'SUM(IF [flow_category] != "dust_spam" THEN [volume_usd] END) / 1000000000000', "real", "measure",
     '*"$"#,##0.0"T"'),
    ("payment_mix_daily", "c_pay_share", "Payment-like share",
     'SUM(IF [flow_category] = "p2p_small_ticket" THEN [transfers] END) / '
     'SUM(IF [flow_category] != "dust_spam" THEN [transfers] END)', "real", "measure", PCT0),
    ("payment_mix_daily", "c_share_tx", "Share of transfers",
     'SUM([transfers]) / MIN({EXCLUDE [flow_category] : SUM([transfers])})', "real", "measure", PCT0),
    ("payment_mix_daily", "c_share_vol", "Share of value",
     'SUM([volume_usd]) / MIN({EXCLUDE [flow_category] : SUM([volume_usd])})', "real", "measure", PCT1),
    ("payment_mix_daily", "c_share_tx_all", "Share of all transfers",
     'SUM([transfers]) / MIN({FIXED : SUM([transfers])})', "real", "measure", PCT1),
    ("payment_mix_daily", "c_share_vol_all", "Share of all value",
     'SUM([volume_usd]) / MIN({FIXED : SUM([volume_usd])})', "real", "measure", "p0.00%"),
    # network
    ("network_daily", "c_fee_med_12m", "Median fee per transfer, last 12 months",
     'MEDIAN(IF [activity_date] >= #2024-07-01# THEN [est_transfer_fee_usd] END)', "real", "measure", USD2),
    # hourly fees
    ("fee_hourly_panel", "c_small_share", "Small share of P2P",
     'SUM([p2p_small_transfers]) / SUM([p2p_transfers])', "real", "measure", PCT0),
    ("fee_hourly_panel", "c_weekday", "Day of week (UTC)",
     "STR(DATEPART('weekday', [hour_ts])) + ' ' + DATENAME('weekday', [hour_ts])", "string", "dimension", None),
    ("fee_hourly_panel", "c_last12", "Last 12 months",
     "[activity_date] >= #2024-07-01#", "boolean", "dimension", None),
    ("fee_hourly_panel", "c_fee_med", "Median fee per transfer",
     "MEDIAN([est_transfer_fee_usd])", "real", "measure", USD2),
    ("fee_hourly_panel", "c_fee_avg", "Average fee per transfer",
     "AVG([est_transfer_fee_usd])", "real", "measure", USD2),
    ("fee_hourly_panel", "c_cheapest_hour_fee", "Cheapest hour of the day: fee",
     "{FIXED [activity_date] : MIN([est_transfer_fee_usd])}", "real", "measure", USD2),
    ("fee_hourly_panel", "c_bill_any", "Monthly fee bill: send any time",
     f"AVG([est_transfer_fee_usd]) * {P}.[p_recipients]", "real", "measure", USD0),
    ("fee_hourly_panel", "c_bill_cheap", "Monthly fee bill: send at the day's cheapest hour",
     f"AVG([Calculation_c_cheapest_hour_fee]) * {P}.[p_recipients]", "real", "measure", USD0),
    ("fee_hourly_panel", "c_saving_year", "Yearly saving from timing payouts",
     f"(AVG([est_transfer_fee_usd]) - AVG([Calculation_c_cheapest_hour_fee])) * {P}.[p_recipients] * 12",
     "real", "measure", USD0),
    ("fee_hourly_panel", "c_fee_pct_payout", "Fee as % of payout (send any time)",
     f"AVG([est_transfer_fee_usd]) / {P}.[p_payout]", "real", "measure", "p0.00%"),
    ("fee_hourly_panel", "c_fee_pct_payout_cheap", "Fee as % of payout (cheapest hour)",
     f"AVG([Calculation_c_cheapest_hour_fee]) / {P}.[p_payout]", "real", "measure", "p0.00%"),
    ("fee_hourly_panel", "c_dencun_window", "In Dencun window",
     "[hour_ts] >= #2023-12-11# AND [hour_ts] < #2024-06-17#", "boolean", "dimension", None),
    ("fee_hourly_panel", "c_small_index", "Small P2P (index, pre-Dencun avg = 1)",
     "SUM([p2p_small_transfers]) / (MIN({FIXED : SUM(IF [hour_ts] >= #2023-12-11# AND [hour_ts] < #2024-03-11# "
     "THEN [p2p_small_transfers] END)}) / 13)", "real", "measure", "#,##0.00"),
    ("fee_hourly_panel", "c_large_index", "Large P2P (index, pre-Dencun avg = 1)",
     "SUM([p2p_large_transfers]) / (MIN({FIXED : SUM(IF [hour_ts] >= #2023-12-11# AND [hour_ts] < #2024-03-11# "
     "THEN [p2p_large_transfers] END)}) / 13)", "real", "measure", "#,##0.00"),
    # lifecycle
    ("activation_funnel", "c_act7", "Activation (sent within 7 days)",
     "SUM([sent_within_7d]) / SUM([new_wallets])", "real", "measure", PCT0),
    ("activation_funnel", "c_ret_m3", "Month-3 retention",
     'SUM(IF [month_3_observed] = "True" THEN [active_month_3] END) / '
     'SUM(IF [month_3_observed] = "True" THEN [new_wallets] END)', "real", "measure", PCT0),
    ("activation_funnel", "c_band", "First receipt",
     'CASE [first_receive_band] WHEN "under_$100" THEN "1 Under $100" WHEN "$100-1K" THEN "2 $100 to $1K" '
     'WHEN "$1K-10K" THEN "3 $1K to $10K" ELSE "4 $10K+" END', "string", "dimension", None),
    ("activation_funnel", "c_new_wallets_m", "New wallets (M)",
     "SUM([new_wallets]) / 1000000", "real", "measure", '*#,##0.0"M"'),
    ("cohort_retention", "c_retention", "Retention",
     "IF MIN([months_since_start]) > 0 THEN SUM([active_wallets]) / SUM([cohort_size]) END", "real", "measure",
     PCT0),
    # segments
    ("segment_mix_monthly", "c_wallet_months_m", "Wallet-months (M)",
     "SUM([wallets]) / 1000000", "real", "measure", '*#,##0.0"M"'),
    ("segment_mix_monthly", "c_seg_vol_t", "Volume sent ($T)",
     "SUM([volume_sent_usd]) / 1000000000000", "real", "measure", '*"$"#,##0.00"T"'),
    # data quality
    ("dq_summary", "c_status", "Status",
     'IF [passed] = "True" THEN "Pass" ELSEIF [severity] = "warn" THEN "Warn" ELSE "Fail" END',
     "string", "dimension", None),
    ("dq_summary", "c_checks", "Checks", "COUNT([check_name])", "integer", "measure", "#,##0"),
]
CALC_BY_ID = {c[1]: c for c in CALCS}

PARAMS = [  # id, caption, datatype, value, min, max, step, format
    ("p_recipients", "Recipients paid per month", "integer", 50000, 1000, 1000000, 1000, "#,##0"),
    ("p_payout", "Average payout ($)", "real", 200, 10, 5000, 10, USD0),
]


def field_name(f: str) -> str:
    return f"[Calculation_{f}]" if f in CALC_BY_ID else f"[{f}]"


# --------------------------------------------------------------------------------------------
# XML helpers
# --------------------------------------------------------------------------------------------
def sub(parent, tag, **attrs):
    return ET.SubElement(parent, tag, {k.replace("__", ":").rstrip("_"): str(v) for k, v in attrs.items()
                                       if v is not None})


def calc_column(parent, c):
    _, cid, caption, formula, dtype, role, fmt = c
    col = sub(parent, "column", caption=caption, datatype=dtype, default_format=None, name=f"[Calculation_{cid}]",
              role=role, type="quantitative" if role == "measure" else "nominal")
    if fmt:
        col.set("default-format", fmt)
    sub(col, "calculation", class_="tableau", formula=formula)
    return col


def datasources(root):
    dss = sub(root, "datasources")
    # parameters
    pds = sub(dss, "datasource", hasconnection="false", inline="true", name="Parameters", version="18.1")
    sub(pds, "aliases", enabled="yes")
    for pid, cap, dtype, val, lo, hi, step, fmt in PARAMS:
        col = sub(pds, "column", caption=cap, datatype=dtype, name=f"[{pid}]", param_domain_type="range",
                  role="measure", type="quantitative", value=val)
        col.set("default-format", fmt)
        col.attrib.pop("param_domain_type", None)
        col.set("param-domain-type", "range")
        sub(col, "calculation", class_="tableau", formula=str(val))
        sub(col, "range", granularity=step, max=hi, min=lo)

    for name in TYPES:
        cols = header(name)
        types = {c: TYPES[name].get(c, "string") for c in cols}
        ds = sub(dss, "datasource", caption=CAPTIONS[name], inline="true", name=ds_id(name), version="18.1")
        conn = sub(ds, "connection", class_="federated")
        ncs = sub(conn, "named-connections")
        nc = sub(ncs, "named-connection", caption=name, name=f"textscan.{name.replace('_', '')}")
        sub(nc, "connection", class_="textscan", directory=DATA_DIR, filename=f"{name}.csv", password="", server="")
        rel = sub(conn, "relation", connection=f"textscan.{name.replace('_', '')}", name=f"{name}.csv",
                  table=f"[{name}#csv]", type="table")
        rcols = sub(rel, "columns", character_set="UTF-8", header="yes", locale="en_US", separator=",")
        for i, c in enumerate(cols):
            sub(rcols, "column", datatype=types[c], name=c, ordinal=i)
        md = sub(conn, "metadata-records")
        for i, c in enumerate(cols):
            r = sub(md, "metadata-record", class_="column")
            for tag, val in [("remote-name", c), ("remote-type", REMOTE[types[c]]), ("local-name", f"[{c}]"),
                             ("parent-name", f"[{name}.csv]"), ("remote-alias", c), ("ordinal", i),
                             ("local-type", types[c]),
                             ("aggregation", "Sum" if types[c] in ("real", "integer") else "Count"),
                             ("contains-null", "true")]:
                sub(r, tag).text = str(val)
        sub(ds, "aliases", enabled="yes")
        for c in cols:  # friendly captions, measure/dimension roles
            role, typ = role_type(types[c], c)
            sub(ds, "column", caption=c.replace("_", " ").capitalize(), datatype=types[c], name=f"[{c}]",
                role=role, type=typ)
        for c in CALCS:
            if c[0] == name:
                calc_column(ds, c)
        if name == "payment_mix_daily":
            _colour_map(ds, "Calculation_c_flow_label", FLOW_COLOURS)


def _colour_map(ds, field, mapping):
    st = sub(ds, "style")
    rule = sub(st, "style-rule", element="mark")
    enc = sub(rule, "encoding", attr="color", field=f"[{field}]", type="palette")
    for k, v in mapping.items():
        m = sub(enc, "map", to=v)
        sub(m, "bucket").text = f'"{k}"'


# --------------------------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------------------------
DERIV = {"none": "None", "sum": "Sum", "avg": "Avg", "tmn": "Month-Trunc", "twk": "Week-Trunc", "usr": "User",
         "cnt": "Count", "tdy": "Day-Trunc"}
KIND = {"nk": "nominal", "qk": "quantitative", "ok": "ordinal"}


class Ref:
    """A field used on a shelf: aggregation/derivation prefix, field id, kind suffix."""

    def __init__(self, ds: str, deriv: str, field: str, kind: str):
        self.ds, self.deriv, self.field, self.kind = ds, deriv, field, kind

    @property
    def inner(self):
        base = field_name(self.field)[1:-1]
        return f"[{self.deriv}:{base}:{self.kind}]"

    def __str__(self):
        return f"[{ds_id(self.ds) if self.ds != 'Parameters' else 'Parameters'}].{self.inner}"


def sheet(root_ws, name, ds, *, rows=(), cols=(), mark="Automatic", color=None, text=None, size=None,
          detail=(), filters=(), title=None, palette=None, params=(), refline=None, fit="entire", fmt_rules=()):
    ws = sub(root_ws, "worksheet", name=name)
    if title is not None:
        lo = sub(ws, "layout-options")
        t = sub(lo, "title")
        ft = sub(t, "formatted-text")
        sub(ft, "run", bold="true", fontsize="13").text = title
    table = sub(ws, "table")
    view = sub(table, "view")
    dsl = sub(view, "datasources")
    sub(dsl, "datasource", caption=CAPTIONS[ds], name=ds_id(ds))
    if params:
        sub(dsl, "datasource", name="Parameters")
    refs = [r for r in [*rows, *cols, color, text, size, *detail] if r is not None] + [f[0] for f in filters]
    if params:
        dep = sub(view, "datasource-dependencies", datasource="Parameters")
        for pid, cap, dtype, val, lo, hi, step, pf in PARAMS:
            if pid in params:
                c = sub(dep, "column", caption=cap, datatype=dtype, name=f"[{pid}]", role="measure",
                        type="quantitative", value=val)
                c.set("param-domain-type", "range")
                sub(c, "calculation", class_="tableau", formula=str(val))
                sub(c, "range", granularity=step, max=hi, min=lo)
    dep = sub(view, "datasource-dependencies", datasource=ds_id(ds))
    types = {c: TYPES[ds].get(c, "string") for c in header(ds)}
    used_base, used_calc = set(), set()

    def collect(f):
        if f in CALC_BY_ID:
            if f in used_calc:
                return
            used_calc.add(f)
            formula = CALC_BY_ID[f][3]
            for other in CALC_BY_ID:
                if f"[Calculation_{other}]" in formula:
                    collect(other)
            for b in types:
                if f"[{b}]" in formula:
                    used_base.add(b)
        else:
            used_base.add(f)

    for r in refs:
        collect(r.field)
    for b in sorted(used_base):
        role, typ = role_type(types[b], b)
        sub(dep, "column", datatype=types[b], name=f"[{b}]", role=role, type=typ)
    for c in CALCS:
        if c[1] in used_calc:
            calc_column(dep, c)
    seen = set()
    for r in refs:
        if r.inner in seen:
            continue
        seen.add(r.inner)
        sub(dep, "column-instance", column=field_name(r.field), derivation=DERIV[r.deriv], name=r.inner,
            pivot="key", type=KIND[r.kind])
    for ref, kind, values in filters:
        if kind == "member":
            fl = sub(view, "filter", class_="categorical", column=str(ref))
            sub(fl, "groupfilter", function="member", level=ref.inner, member=values,
                user__ui_domain="database", user__ui_enumeration="inclusive", user__ui_marker="enumerate")
    sub(view, "aggregation", value="true")

    style = sub(table, "style")
    for el, attr, field, value in fmt_rules:
        rule = sub(style, "style-rule", element=el)
        sub(rule, "format", attr=attr, field=str(field), value=value)
    panes = sub(table, "panes")
    pane = sub(panes, "pane", selection_relaxation_option="selection-relaxation-allow")
    pv = sub(pane, "view")
    sub(pv, "breakdown", value="auto")
    sub(pane, "mark", class_=mark)
    if refline is not None:
        ref_ax, value, label = refline
        rl = sub(pane, "reference-line", axis_column=str(ref_ax), enable_instant_analytics="true",
                 formula="constant", id="refline0", label=label, label_type="custom", scope="per-table",
                 value=value, value_column=str(ref_ax), z_order="1")
        rl.set("fill-above", "false")
    enc = sub(pane, "encodings")
    if color is not None:
        sub(enc, "color", column=str(color))
    if size is not None:
        sub(enc, "size", column=str(size))
    if text is not None:
        sub(enc, "text", column=str(text))
    for d in detail:
        sub(enc, "lod", column=str(d))
    sub(table, "rows").text = shelf(rows)
    sub(table, "cols").text = shelf(cols)
    return ws


def shelf(refs):
    if not refs:
        return None
    if len(refs) == 1:
        return str(refs[0])
    return "(" + " / ".join(str(r) for r in refs) + ")"


DIM_INTS = ("hour_of_day", "day_of_week", "months_since_start")


def role_type(t: str, c: str) -> tuple[str, str]:
    if t in ("real", "integer") and c not in DIM_INTS:
        return "measure", "quantitative"
    if t in ("date", "datetime"):
        return "dimension", "quantitative"
    return "dimension", "ordinal" if c in DIM_INTS else "nominal"


def R(ds, deriv, field, kind):
    return Ref(ds, deriv, field, kind)


def build_sheets(root):
    wss = sub(root, "worksheets")
    pm, nd, fh, af, cr, sm, dq = ("payment_mix_daily", "network_daily", "fee_hourly_panel", "activation_funnel",
                                  "cohort_retention", "segment_mix_monthly", "dq_summary")
    # D1 executive overview
    sheet(wss, "KPI Transfers", pm, mark="Text", text=R(pm, "usr", "c_tx_ex_spam_m", "qk"), title="")
    sheet(wss, "KPI Volume", pm, mark="Text", text=R(pm, "usr", "c_vol_t", "qk"), title="")
    sheet(wss, "KPI Payment share", pm, mark="Text", text=R(pm, "usr", "c_pay_share", "qk"), title="")
    sheet(wss, "KPI Fee", nd, mark="Text", text=R(nd, "usr", "c_fee_med_12m", "qk"), title="")
    sheet(wss, "KPI Activation", af, mark="Text", text=R(af, "usr", "c_act7", "qk"), title="")
    sheet(wss, "KPI Retention", af, mark="Text", text=R(af, "usr", "c_ret_m3", "qk"), title="")
    sheet(wss, "Payment share trend", pm, mark="Line",
          rows=[R(pm, "usr", "c_pay_share", "qk")], cols=[R(pm, "tmn", "activity_date", "qk")],
          title="Small payments are about 30% of transfers, and dip when fees spike")
    # D2 what stablecoins are used for
    sheet(wss, "Flow mix by month", pm, mark="Area",
          rows=[R(pm, "usr", "c_share_tx", "qk")], cols=[R(pm, "tmn", "activity_date", "qk")],
          color=R(pm, "none", "c_flow_label", "nk"),
          title="Share of transfers by flow type, monthly")
    sheet(wss, "Transfers vs value", pm, mark="Bar",
          rows=[R(pm, "none", "c_flow_label", "nk")],
          cols=[R(pm, "usr", "c_share_tx_all", "qk"), R(pm, "usr", "c_share_vol_all", "qk")],
          color=R(pm, "none", "c_flow_label", "nk"),
          title="Most transfers are small payments, but almost all value is large flows")
    sheet(wss, "Segments", sm, mark="Bar",
          rows=[R(sm, "none", "segment", "nk")],
          cols=[R(sm, "usr", "c_wallet_months_m", "qk"), R(sm, "usr", "c_seg_vol_t", "qk")],
          title="Payment-like wallets are the largest segment by count, services move the value")
    # D3 fees
    sheet(wss, "Daily fee", nd, mark="Line",
          rows=[R(nd, "avg", "est_transfer_fee_usd", "qk")], cols=[R(nd, "tdy", "activity_date", "qk")],
          title="Network fee per stablecoin transfer (USD, daily)")
    sheet(wss, "Fee vs small share", fh, mark="Circle",
          rows=[R(fh, "usr", "c_small_share", "qk")], cols=[R(fh, "avg", "est_transfer_fee_usd", "qk")],
          detail=[R(fh, "none", "hour_ts", "nk")],
          title="Small payments thin out as fees rise (each dot is one hour)")
    # D4 Dencun
    sheet(wss, "Dencun small vs large", fh, mark="Line",
          rows=[R(fh, "usr", "c_small_index", "qk"), R(fh, "usr", "c_large_index", "qk")],
          cols=[R(fh, "twk", "hour_ts", "qk")],
          filters=[(R(fh, "none", "c_dencun_window", "nk"), "member", "true")],
          title="Small and large P2P transfers around Dencun, weekly, indexed to the pre-period")
    # D5 lifecycle
    sheet(wss, "Cohort heatmap", cr, mark="Square",
          rows=[R(cr, "tmn", "cohort_month", "ok")], cols=[R(cr, "none", "months_since_start", "ok")],
          color=R(cr, "usr", "c_retention", "qk"), text=R(cr, "usr", "c_retention", "qk"),
          title="Share of each monthly cohort still active N months later")
    sheet(wss, "Retention by first receipt", af, mark="Bar",
          rows=[R(af, "none", "c_band", "nk")], cols=[R(af, "usr", "c_ret_m3", "qk")],
          color=R(af, "none", "primary_token", "nk"), detail=[],
          title="Wallets whose first receipt is $100+ retain better (month-3 retention)")
    sheet(wss, "Activation by first receipt", af, mark="Bar",
          rows=[R(af, "none", "c_band", "nk")], cols=[R(af, "usr", "c_act7", "qk")],
          color=R(af, "none", "primary_token", "nk"),
          title="Activation (sent within 7 days) by first receipt and token")
    # D6 data quality
    sheet(wss, "DQ checks", dq, mark="Bar",
          rows=[R(dq, "none", "dataset", "nk")], cols=[R(dq, "usr", "c_checks", "qk")],
          color=R(dq, "none", "c_status", "nk"),
          title="Automated data quality checks by layer (all passing)")
    # D7 payout planner
    sheet(wss, "Cheapest hours heatmap", fh, mark="Square",
          rows=[R(fh, "none", "c_weekday", "nk")], cols=[R(fh, "none", "hour_of_day", "ok")],
          color=R(fh, "usr", "c_fee_med", "qk"), text=R(fh, "usr", "c_fee_med", "qk"),
          filters=[(R(fh, "none", "c_last12", "nk"), "member", "true")],
          title="Median fee per transfer by day and hour (UTC, last 12 months): lighter is cheaper")
    sheet(wss, "Monthly fee bill", fh, mark="Bar", params=("p_recipients",),
          rows=[R(fh, "usr", "c_bill_any", "qk"), R(fh, "usr", "c_bill_cheap", "qk")],
          cols=[R(fh, "tmn", "hour_ts", "ok")],
          title="Monthly network fee bill for your payouts: any time vs the day's cheapest hour")
    sheet(wss, "KPI Saving", fh, mark="Text", params=("p_recipients",),
          text=R(fh, "usr", "c_saving_year", "qk"),
          filters=[(R(fh, "none", "c_last12", "nk"), "member", "true")], title="")
    sheet(wss, "KPI Fee pct", fh, mark="Text", params=("p_payout",),
          text=R(fh, "usr", "c_fee_pct_payout", "qk"),
          filters=[(R(fh, "none", "c_last12", "nk"), "member", "true")], title="")
    sheet(wss, "KPI Fee pct cheap", fh, mark="Text", params=("p_payout",),
          text=R(fh, "usr", "c_fee_pct_payout_cheap", "qk"),
          filters=[(R(fh, "none", "c_last12", "nk"), "member", "true")], title="")


# --------------------------------------------------------------------------------------------
# Dashboards (1200 x 800, floating layout; coordinates in 1/100000 of width/height)
# --------------------------------------------------------------------------------------------
W, H = 1200, 800
_zid = [10]


def zid():
    _zid[0] += 1
    return _zid[0]


def px(x, y, w, h):
    return dict(x=int(x / W * 100000), y=int(y / H * 100000), w=int(w / W * 100000), h=int(h / H * 100000))


def text_zone(parent, x, y, w, h, runs):
    z = sub(parent, "zone", floating="true", id=zid(), type_v2="text", **px(x, y, w, h))
    z.attrib["type-v2"] = z.attrib.pop("type_v2", "text")
    ft = sub(z, "formatted-text")
    for txt, size, bold, colour in runs:
        r = sub(ft, "run", fontcolor=colour, fontsize=size)
        if bold:
            r.set("bold", "true")
        r.text = txt.replace("\n", "\u00c6\n")
    return z


def sheet_zone(parent, name, x, y, w, h, show_title=True):
    z = sub(parent, "zone", floating="true", id=zid(), name=name, **px(x, y, w, h))
    if not show_title:
        z.set("show-title", "false")
    return z


def param_zone(parent, pid, x, y, w, h):
    z = sub(parent, "zone", floating="true", id=zid(), mode="slider", param=f"[Parameters].[{pid}]", **px(x, y, w, h))
    z.set("type-v2", "paramctrl")
    return z


def kpi(parent, sheet_name, label, x, y, w=180, h=100):
    sheet_zone(parent, sheet_name, x, y + 8, w, 55, show_title=False)
    text_zone(parent, x, y + 62, w, 36, [(label, "10", False, "#666666")])


def dashboard(root_db, name, question, build):
    _zid[0] = 10
    db = sub(root_db, "dashboard", name=name)
    sub(db, "style")
    sub(db, "size", maxheight=H, maxwidth=W, minheight=H, minwidth=W, sizing_mode="fixed")
    zones = sub(db, "zones")
    top = sub(zones, "zone", h=100000, id=2, w=100000, x=0, y=0)
    top.set("type-v2", "layout-basic")
    text_zone(top, 20, 10, 1160, 34, [(name.split(" ", 1)[1], "20", True, "#1f2d3d")])
    text_zone(top, 20, 44, 1160, 26, [("Question: " + question, "12", False, "#4a5568")])
    build(top)
    text_zone(top, 20, 770, 1160, 26, [(FOOTER, "8", False, "#8a94a6")])
    return db


def build_dashboards(root):
    dbs = sub(root, "dashboards")

    def d1(t):
        for i, (s, label) in enumerate([("KPI Transfers", "stablecoin transfers (ex spam)"),
                                        ("KPI Volume", "value moved"),
                                        ("KPI Payment share", "of transfers are payments under $1K"),
                                        ("KPI Fee", "median fee per transfer, last 12 months"),
                                        ("KPI Activation", "of new wallets send within 7 days"),
                                        ("KPI Retention", "of new wallets active in month 3")]):
            kpi(t, s, label, 20 + i * 193, 80)
        sheet_zone(t, "Payment share trend", 20, 200, 1160, 360)
        text_zone(t, 20, 575, 1160, 180, [
            ("What this means: ", "12", True, "#1f2d3d"),
            ("Stablecoin payments on Ethereum are real and steady, about 3 in 10 transfers, but they are a "
             "rounding error in value (0.07% of dollars moved). The share falls when network fees spike "
             "(late 2023, March 2024) and recovers when fees fall. 71% of new wallets 'activate', but most of "
             "them are pass-through addresses, which is why month-3 retention is low. See the Lifecycle "
             "dashboard before setting an activation target.", "12", False, "#1f2d3d")])

    def d2(t):
        sheet_zone(t, "Transfers vs value", 20, 80, 1160, 230)
        sheet_zone(t, "Flow mix by month", 20, 320, 700, 440)
        sheet_zone(t, "Segments", 730, 320, 450, 440)

    def d3(t):
        sheet_zone(t, "Daily fee", 20, 80, 1160, 250)
        sheet_zone(t, "Fee vs small share", 20, 340, 760, 420)
        text_zone(t, 800, 350, 380, 400, [
            ("Elasticity of small payments to fees: -0.149\n", "14", True, "#1f2d3d"),
            ("95% CI -0.163 to -0.135. A 10% higher fee goes with about 1.5% fewer small transfers in that "
             "hour, holding hour-of-week and month fixed (HAC errors).\n\n", "11", False, "#1f2d3d"),
            ("Relative to large transfers: -0.241\n", "14", True, "#1f2d3d"),
            ("Large tickets barely react. The under-$1K share of P2P falls from 62% in the cheapest hours "
             "to 47% in the most expensive decile.\n\n", "11", False, "#1f2d3d"),
            ("Decision: ", "11", True, "#1f2d3d"),
            ("route payouts under $1K to the cheapest rail, and batch or delay them when fees are in the "
             "top two deciles. Use the Payout planner to size the saving.", "11", False, "#1f2d3d")])

    def d4(t):
        sheet_zone(t, "Dencun small vs large", 20, 80, 760, 680)
        text_zone(t, 800, 90, 380, 660, [
            ("Result: inconclusive, and we say so\n\n", "14", True, "#1f2d3d"),
            ("Dencun (13 Mar 2024) cut rollup costs on a known date, a natural experiment. Small tickets are "
             "the treated group, large tickets ($10K+) the control.\n\n", "11", False, "#1f2d3d"),
            ("Difference-in-differences: p = 0.09. Pre-period event-study coefficients drift up to 0.56 log "
             "points, and a placebo date (13 Dec 2023) shows a similar effect. Early March 2024 was a market "
             "surge that moved large tickets, so the two groups were not on parallel paths.\n\n",
             "11", False, "#1f2d3d"),
            ("Decision: ", "11", True, "#1f2d3d"),
            ("do not plan on a Dencun effect. Rely on the fee elasticity instead.", "11", False, "#1f2d3d")])

    def d5(t):
        sheet_zone(t, "Cohort heatmap", 20, 80, 700, 680)
        sheet_zone(t, "Activation by first receipt", 730, 80, 450, 330)
        sheet_zone(t, "Retention by first receipt", 730, 420, 450, 340)

    def d6(t):
        sheet_zone(t, "DQ checks", 20, 80, 760, 680)
        text_zone(t, 800, 90, 380, 660, [
            ("717 automated checks, all passing\n\n", "14", True, "#1f2d3d"),
            ("Every layer is checked on every run: row counts, null keys, hash and address formats, "
             "foreign keys to blocks, ETH/USD plausibility, and gold-to-silver reconciliation (exact on "
             "row count). 63 dbt models and tests pass in the warehouse.\n\n", "11", False, "#1f2d3d"),
            ("Biggest catch: ", "11", True, "#1f2d3d"),
            ("11.9M address-poisoning spam transfers (5.5% of all), excluded from every payment metric. "
             "Left in, they would have made small payments look far bigger than they are.\n\n",
             "11", False, "#1f2d3d"),
            ("Lake to warehouse: ", "11", True, "#1f2d3d"),
            ("Redshift reconciles to the S3 lake exactly on row count and a business measure.",
             "11", False, "#1f2d3d")])

    def d7(t):
        param_zone(t, "p_recipients", 20, 80, 280, 60)
        param_zone(t, "p_payout", 20, 145, 280, 60)
        kpi(t, "KPI Saving", "saved per year by sending at the day's cheapest hour", 320, 80, 280)
        kpi(t, "KPI Fee pct", "fee as % of payout, sending any time", 610, 80, 280)
        kpi(t, "KPI Fee pct cheap", "fee as % of payout, cheapest hour", 900, 80, 280)
        sheet_zone(t, "Monthly fee bill", 20, 215, 560, 545)
        sheet_zone(t, "Cheapest hours heatmap", 590, 215, 590, 545)

    for name, q, fn in [
        ("1 Executive overview", "is stablecoin payment usage real, and is it growing?", d1),
        ("2 What stablecoins are used for", "how much is real payments, and how much is trading and treasury?", d2),
        ("3 Fees and small payments", "do network fees decide whether small payments happen?", d3),
        ("4 Natural experiment Dencun", "did cheaper rollups change payment behaviour on mainnet?", d4),
        ("5 Wallet lifecycle", "do new users stick, and which ones are worth acquiring?", d5),
        ("6 Data quality", "can we trust these numbers?", d6),
        ("7 Payout planner", "what will network fees cost our payouts, and how much does timing save?", d7),
    ]:
        dashboard(dbs, name, q, fn)


def windows(root, sheet_names, dashboard_names):
    w = sub(root, "windows", source_height="30")
    for d in dashboard_names:
        sub(w, "window", class_="dashboard", maximized="true", name=d)
    for s in sheet_names:
        sub(w, "window", class_="worksheet", name=s)


def build() -> Path:
    root = ET.Element("workbook", {"original-version": "18.1", "source-build": "2023.3.0 (20233.23.0905.1512)",
                                   "source-platform": "win", "version": "18.1",
                                   "xmlns:user": "http://www.tableausoftware.com/xml/user"})
    sub(root, "preferences")
    datasources(root)
    build_sheets(root)
    build_dashboards(root)
    sheet_names = [ws.get("name") for ws in root.find("worksheets")]
    dash_names = [d.get("name") for d in root.find("dashboards")]
    windows(root, sheet_names, dash_names)
    xml = ET.tostring(root, encoding="unicode")
    xml = fix_attr_names(xml)
    twb = "<?xml version='1.0' encoding='utf-8' ?>\n" + xml
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(TWB_NAME, twb)
        for f in sorted(EXTRACTS.glob("*.csv")):
            z.write(f, f"{DATA_DIR}/{f.name}")
    (HERE / TWB_NAME).write_text(twb)
    return OUT


def fix_attr_names(xml: str) -> str:
    # python-friendly kwargs -> Tableau attribute names
    for a, b in [("class_=", "class="), ("default_format=", "default-format="), ("character_set=", "character-set="),
                 ("sizing_mode=", "sizing-mode="), ("source_height=", "source-height="),
                 ("selection_relaxation_option=", "selection-relaxation-option="),
                 ("axis_column=", "axis-column="), ("enable_instant_analytics=", "enable-instant-analytics="),
                 ("label_type=", "label-type="), ("value_column=", "value-column="), ("z_order=", "z-order="),
                 ("param_domain_type=", "param-domain-type="), ("type_v2=", "type-v2="),
                 ("user:ui_domain=", "user:ui-domain="), ("user:ui_enumeration=", "user:ui-enumeration="),
                 ("user:ui_marker=", "user:ui-marker=")]:
        xml = xml.replace(" " + a, " " + b)
    return xml


if __name__ == "__main__":
    print(f"wrote {build()}")
