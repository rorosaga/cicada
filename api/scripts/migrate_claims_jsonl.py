"""Convert one bank's legacy YAML claims fences to JSON Lines (DECIDE-1) — run by the person, never automatically.

    api/.venv/bin/python -m api.scripts.migrate_claims_jsonl --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.migrate_claims_jsonl --bank <path> --apply   # one `cicada` commit

The bank is named explicitly; nothing is resolved from the environment's active bank. Prints one JSON object of counts
(never a page name or a claim's words). Exit 0 done, 2 not a bank, 3 refused because Sleep is running or holds the
pages — run it again after the drain. Asks the local backend (``CICADA_PORT``) whether a run is in progress and FAILS
CLOSED, as claim recovery does: only an HTTP 200 whose JSON says ``writing: false`` and a status other than ``running``
lets it write. No backend, a wrong port, an auth or server error, a timeout or a malformed answer all refuse — this
process cannot see Sleep's flag, and the backend's answer is the only guard against a run. A slow or absent answer
is asked again (``PROBE_TRIES``) first, and a refusal says which it was: Sleep running, or the backend slow,
unreachable or unreadable (``backend_problem``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path


#: What one look at ``/sleep/status`` found (a closed set). Only ``IDLE`` lets a command write.
IDLE, SLEEP, SLOW, UNREACHABLE, UNREADABLE = "idle", "sleep", "slow", "unreachable", "unreadable"
#: Each look waits this long; a slow or absent answer is asked again (``PROBE_TRIES`` in all, ``PROBE_RETRY_S``
#: apart) before a command stops — a backend busy for a few seconds is not a running Sleep (2026-10-17: a page
#: rebuild stopped mid-way with "Sleep started" while Sleep was idle and the backend merely slow).
PROBE_TIMEOUT_S = 8.0
PROBE_TRIES = 3
PROBE_RETRY_S = 2.0

_last: dict = {"answer": None}


def _probe_once(environ) -> str:
    import socket
    import urllib.error

    from api.cli import _backend_headers
    from api.services import runtime_layout

    url = f"{runtime_layout.local_backend_url(environ)}/sleep/status"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers=_backend_headers(environ)),
                         timeout=PROBE_TIMEOUT_S) as resp:
            if resp.status != 200:
                return UNREADABLE
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return UNREADABLE                     # it answered: an auth or server error, asking again changes nothing
    except urllib.error.URLError as exc:
        return SLOW if isinstance(exc.reason, (socket.timeout, TimeoutError)) else UNREACHABLE
    except (socket.timeout, TimeoutError):
        return SLOW
    except (ConnectionError, OSError):
        return UNREACHABLE
    except Exception:  # noqa: BLE001 — a malformed answer is "cannot establish that Sleep is idle"
        return UNREADABLE
    if not isinstance(body, dict):
        return UNREADABLE
    if body.get("writing") is False and body.get("status") != "running":
        return IDLE
    if body.get("writing") is True or body.get("status") == "running":
        return SLEEP
    return UNREADABLE


def probe_sleep(environ=None) -> str:
    """What the backend says about Sleep, asking again while it is slow or not answering."""
    environ = os.environ if environ is None else environ
    answer = UNREACHABLE
    for attempt in range(max(1, PROBE_TRIES)):
        answer = _probe_once(environ)
        if answer not in (SLOW, UNREACHABLE):
            break
        if attempt + 1 < PROBE_TRIES:
            time.sleep(PROBE_RETRY_S)
    _last["answer"] = answer
    return answer


def backend_running(environ=None) -> bool:
    """Could Sleep be running or holding the pages? ``True`` unless the backend clearly says it is idle."""
    return probe_sleep(environ) != IDLE


def backend_problem() -> str | None:
    """Why the last :func:`backend_running` could not establish that Sleep is idle, when the reason is the backend
    rather than Sleep (``None`` when it was idle or Sleep was running) — so a stop never says "Sleep started" for a
    backend that was only slow or away."""
    return {
        SLOW: f"the backend did not answer within {PROBE_TIMEOUT_S:g} s ({PROBE_TRIES} tries), so Sleep could not be "
              "confirmed idle",
        UNREACHABLE: f"the backend is not reachable ({PROBE_TRIES} tries) — it may be stopped or restarting, so Sleep "
                     "could not be confirmed idle",
        UNREADABLE: "the backend's answer could not be read (an auth or server error), so Sleep could not be "
                    "confirmed idle",
    }.get(_last["answer"])


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
        print(json.dumps({"refused": backend_problem() or str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
