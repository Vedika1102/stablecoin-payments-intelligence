#!/usr/bin/env bash
# One Spark app per month so local shuffle/spill files are removed between months (small-disk machine).
set -euo pipefail
cd "$(dirname "$0")/.."
export SPARK_DRIVER_MEMORY=${SPARK_DRIVER_MEMORY:-9g}
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
for m in 2025-05-01:2025-05-31 2025-06-01:2025-06-30; do
  log "silver ${m%%:*}..${m##*:}"; python -m lakehouse.jobs.build_silver --start "${m%%:*}" --end "${m##*:}"
done
log "gold"; python -m lakehouse.jobs.build_gold
log "done"
