#!/usr/bin/env bash
#
# verify-skills.sh — re-check the recommended-skill catalog against upstream (G138).
#
# A maintainer runs this by hand when the catalog changes or before a release,
# the way scripts/fetch-logos.sh re-checks the marks. It READS public GitHub
# pages and raw files; it installs nothing and runs nothing it downloads.
# Tests never call it (they never touch the network).
#
#   scripts/verify-skills.sh        exit 0 when every pin, hash and page checks out
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"   # portability: no author-machine path
CATALOG="$REPO/api/data/recommended_skills.json"
PY="$REPO/api/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

"$PY" - "$CATALOG" <<'PYEOF'
import hashlib, json, sys, urllib.request

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "cicada-verify-skills/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, resp.read()

failures = 0
catalog = json.load(open(sys.argv[1], encoding="utf-8"))
for entry in catalog["skills"]:
    checks = [("page", entry["sourceUrl"])]
    if entry.get("terms"):
        checks.append(("terms", entry["terms"]["url"]))
    pin = entry.get("pin") or {}
    if pin:
        checks.append(("commit", f"https://github.com/{pin['repo']}/tree/{pin['sha']}"))
    for label, url in checks:
        try:
            status, _ = fetch(url)
            ok = status == 200
        except Exception as exc:
            ok, status = False, type(exc).__name__
        print(f"{'OK ' if ok else 'BAD'} {entry['id']:<20} {label:<7} {url} ({status})")
        failures += 0 if ok else 1
    if pin.get("skillMdSha256"):
        raw = f"https://raw.githubusercontent.com/{pin['repo']}/{pin['sha']}/{pin['path']}/SKILL.md"
        try:
            _, body = fetch(raw)
            ok = hashlib.sha256(body).hexdigest() == pin["skillMdSha256"]
        except Exception:
            ok = False
        print(f"{'OK ' if ok else 'BAD'} {entry['id']:<20} SKILL.md sha256")
        failures += 0 if ok else 1
sys.exit(1 if failures else 0)
PYEOF
