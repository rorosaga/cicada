"""Give pages outside the closed type set of 10 a type inside it — run by the person, never automatically.

    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path>                  # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path> --list           # + each page id, old → new
    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path> --apply          # one `cicada` commit
    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path> --apply --as <id>=project --as <id>=tool

The mapping and the rails are in ``api.services.entity_type_repair``. ``--as`` overrides the mapping for one page
(repeatable; the type must be one Stage 1 may produce). ``--list`` output is for the person's own terminal — never
paste it into the repo or a PR.

The bank is named explicitly; nothing is resolved from the environment's active bank. Exit 0 done, 2 not a bank or a
bad ``--as``, 3 refused because Sleep is running or holds the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.scripts.migrate_claims_jsonl import backend_running


def _sleep_running() -> bool:
    """``backend_running``, but an unreachable backend is said as such, never as a Sleep run."""
    import os
    import urllib.request

    from api.cli import _backend_headers
    from api.services import entity_type_repair, runtime_layout

    url = f"{runtime_layout.local_backend_url(os.environ)}/healthz"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers=_backend_headers(os.environ)), timeout=4):
            pass
    except Exception as exc:  # noqa: BLE001 — any failure means the backend cannot answer
        raise entity_type_repair.SleepRunning(
            "the backend is unreachable; start Cicada and run again (the repair asks it whether Sleep is idle)") from exc
    return backend_running()


def _overrides(values: list[str]) -> dict[str, str]:
    out = {}
    for value in values or []:
        page, sep, kind = value.partition("=")
        if not sep or not page.strip() or not kind.strip():
            raise ValueError(f"--as takes <id>=<type>, got {value!r}")
        out[page.strip()] = kind.strip()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="repair_entity_types", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/)")
    parser.add_argument("--apply", action="store_true", help="retype and commit; without it, report counts only")
    parser.add_argument("--list", action="store_true", help="dry run: also print each page id with its old and new type")
    parser.add_argument("--as", dest="overrides", action="append", default=[], metavar="ID=TYPE",
                        help="use this type for this page instead of the mapping (repeatable)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2

    from api.services import entity_type_repair as repair

    try:
        overrides = _overrides(args.overrides)
        if not args.apply:
            result = repair.survey(bank, overrides=overrides)
            out = result.counts()
            if args.list:
                out["pages_to_retype"] = result.listing()
            print(json.dumps(out, ensure_ascii=False))
            return 0
        result = repair.apply(bank, sleep_running=_sleep_running, overrides=overrides)
    except (ValueError, repair.BadOverride) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except repair.SleepRunning as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    print(json.dumps(result.counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
