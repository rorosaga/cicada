#!/usr/bin/env bash
#
# check-census.sh — G61 phase 2 S2: how much of a bank's pending inbox a source
# could answer, as counts only (spec §15: the coverage gate for S3–S8).
#
# Read-only: it loads the inbox through the same code `GET /inbox/check-census`
# runs, writes nothing, fetches nothing, calls no model. Its output is enum keys
# and counts — no item id, page id, link or host — so it can be pasted into a PR
# or a backlog row as it is (the privacy rule).
#
#   scripts/check-census.sh <bank-dir>
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"   # portability: no author-machine path
BANK="${1:-}"
if [[ -z "$BANK" || ! -d "$BANK/inbox" ]]; then
  echo "usage: scripts/check-census.sh <bank-dir>   (a bank: a directory with an inbox/)" >&2
  exit 2
fi
BANK="$(cd "$BANK" && pwd)"
PY="$REPO/api/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

cd "$REPO"
"$PY" - "$BANK" <<'PYEOF'
import json
import sys
from pathlib import Path

from api.services import source_check

print(json.dumps(source_check.census(Path(sys.argv[1])), indent=2))
PYEOF
