#!/usr/bin/env bash
# Sequential local backfill (one Spark app at a time to fit a 16 GB machine).
set -euo pipefail
cd "$(dirname "$0")/.."
export SPARK_DRIVER_MEMORY=${SPARK_DRIVER_MEMORY:-9g}
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
log "bronze $BRONZE_START..$END";  python -m lakehouse.jobs.ingest_bronze --start "$BRONZE_START" --end "$END"
log "silver $SILVER_START..$END";  python -m lakehouse.jobs.build_silver --start "$SILVER_START" --end "$END"
log "gold";                        python -m lakehouse.jobs.build_gold
log "done"
