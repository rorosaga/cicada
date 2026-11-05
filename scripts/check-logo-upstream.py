#!/usr/bin/env python3
"""check-logo-upstream.py — which marks in the set differ from what their `source_url` serves today.

A maintainer's release step (docs/RELEASING.md), by hand on purpose: a changed mark never lands unreviewed, so this only
prints. It writes nothing, and the bytes it downloads are hashed in memory and never parsed or saved.

A source matches when the bytes served hash to its `sha256` or to its `upstream_sha256`: what that URL served at the
last review, recorded when the bytes differ from the committed file but the picture does not (a re-encode, or Substack's
added fill). For a line it prints: download the URL into its own empty folder and view old and new side by side. The same
picture means recording the new hash as `upstream_sha256`; a redraw goes through `scripts/build-logo-set.py`.

Exit 0 when every reachable source matches, 1 when one differs. An unreachable source is printed and does not fail.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SET = Path(__file__).resolve().parent.parent / "app/assets/logo-set/manifest.json"
MAX_BYTES = 16 * 1024 * 1024
# Wikimedia refuses an empty User-Agent and asks for a contact URL; the other sites serve the same public icon to it.
HEADERS = {"User-Agent": "Mozilla/5.0 (CicadaLogoCheck; +https://github.com/rorosaga/cicada)"}


def served_sha(url: str) -> str:
    # Two Commons sources name the file's description page; the file itself is one redirect away.
    url = url.replace("commons.wikimedia.org/wiki/File:", "commons.wikimedia.org/wiki/Special:FilePath/")
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - our own manifest's https URLs
        return hashlib.sha256(response.read(MAX_BYTES)).hexdigest()


def check(logo: dict) -> tuple[str, str]:
    known = {logo["sha256"], logo.get("upstream_sha256")}
    try:
        return ("same" if served_sha(logo["source_url"]) in known else "DIFFERS"), logo["slug"]
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"unreachable ({type(exc).__name__})", logo["slug"]


def main() -> int:
    logos = {logo["slug"]: logo for logo in json.loads(SET.read_text(encoding="utf-8"))["logos"]}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, logos.values()))
    differs = 0
    for verdict, slug in sorted(results, key=lambda r: r[1]):
        if verdict != "same":
            print(f"{verdict}  {slug}  {logos[slug]['source_url']}")
            differs += verdict == "DIFFERS"
    print(f"{len(results)} sources: {differs} differ upstream")
    return 1 if differs else 0


if __name__ == "__main__":
    sys.exit(main())
