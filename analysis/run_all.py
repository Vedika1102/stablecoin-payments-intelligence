"""Run every analysis and write reports/summary.json (the numbers quoted in the memo)."""

from __future__ import annotations

import json

import pandas as pd

from analysis import q1_payment_mix, q2_fee_elasticity, q3_dencun_did, q4_wallet_lifecycle
from analysis.common import REPORTS


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if not isinstance(v, pd.DataFrame)}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    try:
        return float(o)
    except (TypeError, ValueError):
        return o


def main() -> None:
    out = {
        "q1": q1_payment_mix.main(),
        "q2": q2_fee_elasticity.main(),
        "q3": q3_dencun_did.main(),
        "q4": q4_wallet_lifecycle.main(),
    }
    (REPORTS / "summary.json").write_text(json.dumps(_clean(out), indent=2))
    print("wrote reports/summary.json")


if __name__ == "__main__":
    main()
