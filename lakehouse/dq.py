"""Lightweight data quality framework for the Spark jobs.

Each check returns a result row (dataset, check, severity, passed, observed, threshold, run_ts).
Results are appended to the lake's _dq_results table (queried by Athena / the dashboard) and the
job fails if any `error` check fails. On AWS the same rules are also expressed in DQDL for
Glue Data Quality (see aws/glue/dq_rules.dqdl).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


@dataclass
class CheckResult:
    dataset: str
    check: str
    severity: str        # error | warn
    passed: bool
    observed: float
    threshold: str
    partition: str
    run_ts: str


class DQRunner:
    def __init__(self, spark: SparkSession, dataset: str, partition: str):
        self.spark, self.dataset, self.partition = spark, dataset, partition
        self.results: list[CheckResult] = []
        self.run_ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def _add(self, check, severity, passed, observed, threshold):
        self.results.append(CheckResult(self.dataset, check, severity, bool(passed), float(observed),
                                        str(threshold), self.partition, self.run_ts))

    # ---- checks -------------------------------------------------------------------------
    def row_count_min(self, df: DataFrame, minimum: int, severity="error"):
        n = df.count()
        self._add("row_count_min", severity, n >= minimum, n, f">= {minimum}")
        return n

    def not_null(self, df: DataFrame, cols: list[str], severity="error"):
        row = df.select([F.sum(F.col(c).isNull().cast("int")).alias(c) for c in cols]).first()
        for c in cols:
            v = row[c] or 0
            self._add(f"not_null:{c}", severity, v == 0, v, "== 0")

    def unique(self, df: DataFrame, keys: list[str], severity="error"):
        dupes = df.groupBy(*keys).count().where("count > 1").count()
        self._add(f"unique:{'+'.join(keys)}", severity, dupes == 0, dupes, "== 0")

    def regex_match_rate(self, df: DataFrame, col: str, pattern: str, min_rate=1.0, severity="error"):
        r = df.select(F.avg(F.col(col).rlike(pattern).cast("double")).alias("r")).first()["r"] or 0.0
        self._add(f"regex:{col}", severity, r >= min_rate, r, f">= {min_rate}")

    def in_range(self, df: DataFrame, col: str, lo=None, hi=None, severity="error"):
        cond = F.lit(False)
        if lo is not None:
            cond = cond | (F.col(col) < lo)
        if hi is not None:
            cond = cond | (F.col(col) > hi)
        bad = df.where(cond).count()
        self._add(f"range:{col}", severity, bad == 0, bad, f"[{lo}, {hi}]")

    def contiguous_sequence(self, df: DataFrame, col: str, severity="error"):
        """No gaps in a monotonically increasing id (e.g. block numbers in a day)."""
        r = df.agg(F.min(col).alias("lo"), F.max(col).alias("hi"), F.countDistinct(col).alias("n")).first()
        expected = (r["hi"] - r["lo"] + 1) if r["lo"] is not None else 0
        missing = expected - (r["n"] or 0)
        self._add(f"contiguous:{col}", severity, missing == 0, missing, "== 0 missing")

    def referential(self, child: DataFrame, parent: DataFrame, child_key: str, parent_key: str, severity="error"):
        orphans = child.select(child_key).distinct().join(
            parent.select(F.col(parent_key).alias(child_key)).distinct(), child_key, "left_anti").count()
        self._add(f"fk:{child_key}", severity, orphans == 0, orphans, "== 0 orphans")

    def custom(self, name: str, passed: bool, observed: float, threshold: str, severity="error"):
        self._add(name, severity, passed, observed, threshold)

    # ---- output -------------------------------------------------------------------------
    def publish(self, dq_path: str, raise_on_error: bool = True) -> list[CheckResult]:
        rows = [asdict(r) for r in self.results]
        if rows:
            (self.spark.createDataFrame(rows).withColumn("run_date", F.to_date(F.lit(self.run_ts[:10])))
             .write.mode("append").partitionBy("dataset").parquet(dq_path))
        failed = [r for r in self.results if not r.passed]
        for r in self.results:
            flag = "PASS" if r.passed else ("FAIL" if r.severity == "error" else "WARN")
            print(f"  [{flag}] {r.dataset}.{r.check} observed={r.observed:g} expected {r.threshold}")
        if raise_on_error and any(r.severity == "error" for r in failed):
            raise RuntimeError(f"DQ failed for {self.dataset} {self.partition}: "
                               + ", ".join(r.check for r in failed if r.severity == "error"))
        return self.results
