import datetime as dt

import pytest

from lakehouse.jobs.build_silver import check_registry_fresh


def _registry(spark, last_created: str):
    return spark.createDataFrame(
        [("0x" + "a" * 40, dt.datetime.fromisoformat(last_created))], "address string, created_at timestamp")


def test_fresh_registry_passes(spark):
    check_registry_fresh(_registry(spark, "2025-06-30 23:59:00"), dt.date(2025, 6, 30))


def test_stale_registry_fails(spark):
    with pytest.raises(RuntimeError, match="RegistryStale"):
        check_registry_fresh(_registry(spark, "2024-03-31 12:00:00"), dt.date(2025, 6, 30))
