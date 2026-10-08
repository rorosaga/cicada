"""Convert one bank's legacy YAML claims fences to JSON Lines (DECIDE-1) — run by the person, never automatically.

    api/.venv/bin/python -m api.scripts.migrate_claims_jsonl --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.migrate_claims_jsonl --bank <path> --apply   # one `cicada` commit

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of counts
(never a page name or a claim's words). Exit 0 done, 2 not a bank, 3 refused because Sleep is running or holds the
pages — run it again after the drain. Asks the local backend (``CICADA_PORT``) whether a run is in progress, the way the
stdio MCP server asks before it commits: no backend answering means no run; a backend too slow to answer counts as one.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path


def backend_running(environ=None) -> bool:
    """Is the local backend running Sleep (``status: running``) or holding the pages (``writing``)?"""
    from api.cli import _backend_headers
    from api.services import runtime_layout

    environ = os.environ if environ is None else environ
    url = f"{runtime_layout.backend_url(environ)}/sleep/status"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers=_backend_headers(environ)), timeout=2) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (TimeoutError, socket.timeout):
        return True
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError as exc:
        return isinstance(exc.reason, (TimeoutError, socket.timeout))
    return bool(body.get("writing")) or body.get("status") == "running"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_claims_jsonl", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="convert and commit; without it, report counts only")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import claims_jsonl_migration as mig

    if not args.apply:
        print(json.dumps(mig.survey(bank).counts()))
        return 0
    try:
        result = mig.apply(bank, sleep_running=backend_running)
    except mig.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
