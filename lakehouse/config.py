"""Pipeline configuration. Every path can point at local disk or S3; the code does not care."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# AWS Public Blockchain Data (Registry of Open Data on AWS), us-east-2, Parquet partitioned by date=
PUBLIC_SOURCE = "s3a://aws-public-blockchain/v1.0/eth"


@dataclass(frozen=True)
class Paths:
    source: str = os.environ.get("SOURCE_ROOT", PUBLIC_SOURCE)
    lake: str = os.environ.get("LAKE_ROOT", str(ROOT / "data" / "lake"))

    @property
    def bronze(self) -> str:
        return f"{self.lake}/bronze"

    @property
    def silver(self) -> str:
        return f"{self.lake}/silver"

    @property
    def gold(self) -> str:
        return f"{self.lake}/gold"

    @property
    def dq(self) -> str:
        return f"{self.lake}/_dq_results"


def load_tokens() -> list[dict]:
    path = ROOT / "config" / "tokens.csv"
    if not path.exists():          # on Glue, --extra-files lands tokens.csv in the working directory
        path = Path("tokens.csv")
    with open(path) as fh:
        return list(csv.DictReader(fh))


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Ticket-size buckets in USD, used across silver, gold, dbt and the dashboard
# Transfers under one cent are almost entirely "address poisoning" spam (zero-value transferFrom
# calls that plant look-alike addresses in a victim's history). They get their own bucket and are
# excluded from payment metrics.
TICKET_BUCKETS = [
    (0, 0.01, "0_dust_<$0.01"),
    (0.01, 10, "a_<$10"),
    (10, 100, "b_$10-100"),
    (100, 1_000, "c_$100-1K"),
    (1_000, 10_000, "d_$1K-10K"),
    (10_000, 100_000, "e_$10K-100K"),
    (100_000, None, "f_$100K+"),
]

# Price oracle: Uniswap v3 USDC/WETH 0.05% pool. ETH/USD is derived from its swap legs so that
# network fees can be expressed in USD without any off-chain price feed.
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
UNISWAP_USDC_WETH_POOL = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"
ERC20_TRANSFER_GAS = 65_000  # typical gas used by a USDC/USDT transfer
