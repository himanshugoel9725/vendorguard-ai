#!/usr/bin/env bash
# Memory demo: nimbara-hr year 1, then year 2, then the diff and a question, all offline.
# Uses the mock LLM and its own state folder (.vendorguard/demo), so it is free and repeatable.
set -euo pipefail

DEMO_DIR="${DEMO_DIR:-.vendorguard/demo}"
rm -rf "$DEMO_DIR"
export VG_LLM__PROVIDER=mock
export VG_EMBEDDINGS__PROVIDER=none
export VG_CACHE__ENABLED=false
export VG_PATHS__RUNS_DIR="$DEMO_DIR/runs"
export VG_PATHS__STATE_DIR="$DEMO_DIR/state"
export VG_MEMORY__SQLITE_PATH="$DEMO_DIR/state/memory.db"

VG="uv run --no-sync vg"
echo "== 1. Assess nimbara-hr (year 1) =="
$VG assess --sample nimbara-hr
echo
echo "== 2. Assess nimbara-hr (year 2): the diff is computed against year 1 =="
$VG assess --sample nimbara-hr-y2
echo
echo "== 3. History kept in memory =="
$VG vendors list
$VG vendors history nimbara-hr
echo
echo "== 4. Ask =="
$VG ask nimbara-hr "What changed for nimbara-hr?"
echo
echo "Reports: $DEMO_DIR/runs/<run id>/report.html (the year-2 report has the diff section)"
