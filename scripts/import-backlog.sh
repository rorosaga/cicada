#!/usr/bin/env bash
#
# import-backlog.sh — G150 R-B15: file a markdown backlog (G-row table rows
# and/or `### G<n>` sections) into ONE project's backlog in a bank, keeping
# ids and statuses. Idempotent: an id already on the backlog is skipped, so a
# second run changes nothing and commits nothing. What it creates lands in one
# `Backlog import` commit as the person (`Cicada-Author: user`, trigger
# `user/backlog_import`).
#
# It writes the named bank directly, in-process, so it asks the local backend
# first and refuses (exit 1, nothing written) while a Sleep cycle runs — that
# cycle's `git add -A` would take the files under its own author — and refuses
# a demo bank. `CICADA_BACKEND_URL` (default http://127.0.0.1:8000) names the
# backend to ask. Its output is counts and ids only — never a title or a
# description — so it can be pasted anywhere.
#
#   scripts/import-backlog.sh <bank-dir> <project-id> <file.md> [prefix]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"   # portability: no author-machine path
BANK="${1:-}"
PROJECT="${2:-}"
FILE="${3:-}"
PREFIX="${4:-G}"
if [[ -z "$BANK" || -z "$PROJECT" || -z "$FILE" || ! -d "$BANK/entities" || ! -f "$FILE" ]]; then
  echo "usage: scripts/import-backlog.sh <bank-dir> <project-id> <file.md> [prefix]" >&2
  exit 2
fi
BANK="$(cd "$BANK" && pwd)"
FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"
PY="$REPO/api/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

cd "$REPO"
"$PY" - "$BANK" "$PROJECT" "$FILE" "$PREFIX" <<'PYEOF'
import json
import os
import sys
from pathlib import Path

from api.services import backlog_import

report = backlog_import.import_file(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), prefix=sys.argv[4],
                                    backend_url=os.environ.get("CICADA_BACKEND_URL") or None)
print(json.dumps({"created": len(report.created), "skipped": len(report.skipped), "failed": report.failed,
                  "error": report.error}))
sys.exit(1 if report.error or report.failed else 0)
PYEOF
