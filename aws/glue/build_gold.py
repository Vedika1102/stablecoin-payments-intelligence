"""Glue 5.0 entry point. Glue passes --SOURCE_ROOT/--LAKE_ROOT as job args; expose them as env
vars for lakehouse.config, then run the same main() used locally."""
import os
import sys

for key in ("SOURCE_ROOT", "LAKE_ROOT"):
    if f"--{key}" in sys.argv:
        os.environ[key] = sys.argv[sys.argv.index(f"--{key}") + 1]
os.environ.setdefault("GLUE_VERSION", "5.0")

from lakehouse.jobs.build_gold import main  # noqa: E402

main()
