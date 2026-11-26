"""Pure DataFrame -> DataFrame transforms. No I/O, so each one is unit-tested on tiny fixtures."""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from lakehouse.config import TICKET_BUCKETS


def normalize_address(col: Column) -> Column:
    """Topic-encoded addresses arrive left-padded to 32 bytes ('0x' + 64 hex).
    The real address is the last 20 bytes. Return canonical lowercase '0x' + 40 hex."""
    hexpart = F.regexp_replace(F.lower(col), r"^0x", "")
    return F.when(col.isNull(), F.lit(None)).otherwise(F.concat(F.lit("0x"), F.substring(hexpart, -40, 40)))


def address_padding_is_clean(col: Column) -> Column:
    """True when the 12 padding bytes are zero, i.e. the value really is an address."""
    hexpart = F.regexp_replace(F.lower(col), r"^0x", "")
    return hexpart.rlike(r"^(0{24})?[0-9a-f]{40}$")


def scale_amount(raw: Column, decimals: Column) -> Column:
    """Raw token units -> human units. Source stores the uint256 as DOUBLE (precision ~15-16
    significant digits), which is fine for USD analytics but noted in the data dictionary."""
    return raw / F.pow(F.lit(10.0), decimals.cast("double"))


def ticket_bucket(amount_usd: Column) -> Column:
    expr = None
    for lo, hi, label in TICKET_BUCKETS:
        cond = (amount_usd >= lo) if hi is None else ((amount_usd >= lo) & (amount_usd < hi))
        expr = F.when(cond, label) if expr is None else expr.when(cond, label)
    return expr.otherwise("z_unknown")


def dedupe_latest(df: DataFrame, keys: list[str], order_col: str) -> DataFrame:
    """Keep one row per business key, the most recently modified one (source re-publishes rows)."""
    w = Window.partitionBy(*keys).orderBy(F.col(order_col).desc_nulls_last())
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


def transfer_kind(from_addr: Column, to_addr: Column, zero: str) -> Column:
    return (F.when(from_addr == zero, "mint")
            .when(to_addr == zero, "burn")
            .otherwise("transfer"))
