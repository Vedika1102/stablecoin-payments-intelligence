"""Unit tests for the PySpark transforms on tiny, hand-checked fixtures (no network)."""

from pyspark.sql import functions as F

from lakehouse.config import ZERO_ADDRESS
from lakehouse.transforms import (
    address_padding_is_clean,
    dedupe_latest,
    normalize_address,
    scale_amount,
    ticket_bucket,
    transfer_kind,
)

PADDED = "0x000000000000000000000000fbaf8cac9eb7a4729702a1b0a5d4b1d47b0e7d2c"


def test_normalize_address_strips_32_byte_padding(spark):
    df = spark.createDataFrame([(PADDED,), ("0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD",), (None,)], "a string")
    out = [r[0] for r in df.select(normalize_address(F.col("a"))).collect()]
    assert out == ["0xfbaf8cac9eb7a4729702a1b0a5d4b1d47b0e7d2c", "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", None]


def test_padding_check_flags_non_address_topics(spark):
    dirty = "0x00000000000000000000ff00fbaf8cac9eb7a4729702a1b0a5d4b1d47b0e7d2c"
    df = spark.createDataFrame([(PADDED,), (dirty,)], "a string")
    assert [r[0] for r in df.select(address_padding_is_clean(F.col("a"))).collect()] == [True, False]


def test_scale_amount_uses_token_decimals(spark):
    df = spark.createDataFrame([(2_000_000.0, 6), (1.5e18, 18)], "v double, d int")
    assert [r[0] for r in df.select(scale_amount(F.col("v"), F.col("d"))).collect()] == [2.0, 1.5]


def test_ticket_bucket_edges(spark):
    df = spark.createDataFrame([(0.0,), (0.009,), (0.5,), (10.0,), (999.99,), (1000.0,), (250000.0,)], "x double")
    got = [r[0] for r in df.select(ticket_bucket(F.col("x"))).collect()]
    assert got == ["0_dust_<$0.01", "0_dust_<$0.01", "a_<$10", "b_$10-100", "c_$100-1K", "d_$1K-10K", "f_$100K+"]


def test_dedupe_keeps_latest_version(spark):
    df = spark.createDataFrame(
        [("0xa", 1, "2024-01-01", 5.0), ("0xa", 1, "2024-01-03", 6.0), ("0xa", 2, "2024-01-01", 7.0)],
        "h string, i int, lm string, v double")
    out = sorted((r.h, r.i, r.v) for r in dedupe_latest(df, ["h", "i"], "lm").collect())
    assert out == [("0xa", 1, 6.0), ("0xa", 2, 7.0)]


def test_transfer_kind(spark):
    df = spark.createDataFrame([(ZERO_ADDRESS, "0xb"), ("0xb", ZERO_ADDRESS), ("0xb", "0xc")], "f string, t string")
    got = [r[0] for r in df.select(transfer_kind(F.col("f"), F.col("t"), ZERO_ADDRESS)).collect()]
    assert got == ["mint", "burn", "transfer"]
