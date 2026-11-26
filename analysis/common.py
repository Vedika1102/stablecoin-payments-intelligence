"""Shared helpers: warehouse connection, chart style, and markdown report writing."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = Path(os.environ.get("WAREHOUSE_PATH", ROOT / "warehouse" / "analytics.duckdb"))
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# Validated categorical palette (fixed order) and text inks
SERIES = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"]
INK, INK_2, GRID = "#191919", "#666666", "#e6e6e6"

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "savefig.bbox": "tight",
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2,
    "axes.prop_cycle": matplotlib.cycler(color=SERIES), "legend.frameon": False,
    "text.color": INK,
})


LAKE = Path(os.environ.get("LAKE_ROOT", ROOT / "data" / "lake"))


def connect() -> duckdb.DuckDBPyConnection:
    if not WAREHOUSE.exists():
        raise SystemExit(f"Warehouse not found at {WAREHOUSE}. Run `make warehouse` first.")
    # dbt staging views point at the lake with paths relative to dbt/, so resolve them from there
    os.chdir(ROOT / "dbt")
    return duckdb.connect(str(WAREHOUSE), read_only=True)


def df_to_md(df, floatfmt: str = "{:,.4f}") -> str:
    """Render a DataFrame as a GitHub markdown table without extra dependencies."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, float) and v.is_integer() and abs(v) >= 100:
                cells.append(f"{v:,.0f}")         # counts that came back as floats
            elif isinstance(v, float):
                cells.append(floatfmt.format(v))
            elif isinstance(v, int):
                cells.append(f"{v:,}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def pp(x: float, d: int = 2) -> str:
    return f"{x * 100:+.{d}f} pp"


def write_report(name: str, text: str) -> Path:
    path = REPORTS / name
    path.write_text(text)
    print(f"wrote {path.relative_to(ROOT)}")
    return path


def fmt_int(x) -> str:
    return f"{int(round(x)):,}"


def fmt_usd(x, d: int = 2) -> str:
    return f"${x:,.{d}f}"
