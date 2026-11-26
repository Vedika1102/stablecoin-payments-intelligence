"""SparkSession that behaves the same locally and on AWS Glue 5.0 / EMR Serverless (Spark 3.5).

Locally it reads the public AWS bucket directly over s3a with anonymous credentials, so the
pipeline processes the real data in place, exactly as a Glue job would with s3://.
"""

from __future__ import annotations

import os

from pyspark.sql import SparkSession

COMMON_CONF = {
    "spark.sql.session.timeZone": "UTC",
    "spark.sql.adaptive.enabled": "true",                     # AQE: runtime partition coalescing + skew joins
    "spark.sql.adaptive.coalescePartitions.enabled": "true",
    "spark.sql.adaptive.skewJoin.enabled": "true",
    "spark.sql.sources.partitionOverwriteMode": "dynamic",    # re-running a day replaces only that day
    "spark.sql.parquet.compression.codec": "zstd",
    "spark.sql.files.maxPartitionBytes": str(256 * 1024 * 1024),
    "spark.sql.parquet.filterPushdown": "true",
}

LOCAL_S3A_CONF = {
    "spark.hadoop.fs.s3a.aws.credentials.provider": "org.apache.hadoop.fs.s3a.AnonymousAWSCredentialsProvider",
    "spark.hadoop.fs.s3a.endpoint": "s3.us-east-2.amazonaws.com",
    "spark.hadoop.fs.s3a.endpoint.region": "us-east-2",
    "spark.hadoop.fs.s3a.connection.maximum": "64",
    "spark.hadoop.fs.s3a.experimental.input.fadvise": "random",  # columnar reads: fetch only needed byte ranges
}


def on_aws() -> bool:
    return "GLUE_VERSION" in os.environ or "EMR_RELEASE_LABEL" in os.environ


def get_spark(app_name: str) -> SparkSession:
    builder = SparkSession.builder.appName(app_name)
    if not on_aws():
        builder = (builder.master(os.environ.get("SPARK_MASTER", "local[*]"))
                   .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "10g"))
                   .config("spark.sql.shuffle.partitions", os.environ.get("SPARK_SHUFFLE_PARTITIONS", "32"))
                   .config("spark.ui.showConsoleProgress", "false"))
        for k, v in LOCAL_S3A_CONF.items():
            builder = builder.config(k, v)
    for k, v in COMMON_CONF.items():
        builder = builder.config(k, v)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark
