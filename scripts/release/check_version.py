#!/usr/bin/env python3
"""Judge a release's version (G182, TODO ruling 19) — the one place CI and `make release` ask.

    check_version.py agree [--root DIR] [--info-plist PATH] [--latest-json PATH]
    git ls-remote --tags --refs origin 'refs/tags/v*' | check_version.py plan [--root DIR] [--dry-run]

`agree` holds every file that stamps a version to `VERSION` (api/pyproject.toml, uv.lock's cicada-api entry, and,
when given, a built app's CFBundleShortVersionString and a release's latest.json) and exits 1 naming the one that
disagrees. `plan` reads tags (ls-remote lines or bare names) on stdin and prints GitHub outputs:

    version=X.Y.Z   status=released|new|behind   latest=true|false   previous=vA.B.C

`released`: `v$VERSION` already exists — publish nothing. `new`: greater than every tag — publish, as latest.
Anything else fails loudly (exit 1), except under --dry-run, which reports `behind` so a dry run still builds.
Stdlib only, and no 3.10+ syntax: it runs on whatever python3 a runner or a Mac has first on PATH.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


class VersionError(Exception):
    pass


class Plan(NamedTuple):
    version: str
    status: str      # released | new | behind
    latest: bool
    previous: str    # the highest existing tag below VERSION ("" when none or nothing to publish)


def key(version: str) -> Tuple[int, int, int]:
    m = SEMVER.fullmatch(version)
    if not m:
        raise VersionError(f"not a release version (X.Y.Z): {version!r}")
    return tuple(int(part) for part in m.groups())  # type: ignore[return-value]


def parse_tags(text: str) -> List[str]:
    """`vX.Y.Z` tags from `git ls-remote --tags` output or one name per line, semver-ordered; others ignored."""
    tags = set()
    for line in text.splitlines():
        ref = line.split()[-1] if line.strip() else ""
        name = ref.rsplit("refs/tags/", 1)[-1]
        if TAG.fullmatch(name):
            tags.add(name)
    return sorted(tags, key=lambda t: key(t[1:]))


def plan(version: str, tags: List[str], dry_run: bool = False) -> Plan:
    mine = key(version)
    tag = f"v{version}"
    if tag in tags:
        return Plan(version, "released", False, "")
    highest = max(tags, key=lambda t: key(t[1:])) if tags else ""
    if highest and key(highest[1:]) >= mine:
        if dry_run:
            return Plan(version, "behind", False, highest)
        raise VersionError(
            f"VERSION {version} is not greater than {highest}, the latest release — bump it with "
            f"`make release VERSION=x.y.z` (an older-line release is never published by CI)")
    return Plan(version, "new", True, highest)


def _read(root: Path, rel: str) -> str:
    path = root / rel
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VersionError(f"{rel}: {exc.strerror}") from None


def _pyproject_version(text: str) -> Optional[str]:
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    m = section and re.search(r'^version\s*=\s*"([^"]*)"', section.group(1), re.M)
    return m.group(1) if m else None


def _lock_version(text: str) -> Optional[str]:
    m = re.search(r'^name = "cicada-api"\nversion = "([^"]*)"', text, re.M)
    return m.group(1) if m else None


def agree(root: Path, info_plist: Optional[Path] = None, latest_json: Optional[Path] = None) -> str:
    version = _read(root, "VERSION").strip()
    key(version)
    found = {
        "api/pyproject.toml": _pyproject_version(_read(root, "api/pyproject.toml")),
        "api/uv.lock (cicada-api)": _lock_version(_read(root, "api/uv.lock")),
    }
    if info_plist is not None:
        with open(info_plist, "rb") as fh:
            found[f"{info_plist} CFBundleShortVersionString"] = plistlib.load(fh).get("CFBundleShortVersionString")
    if latest_json is not None:
        found[f"{latest_json.name} ({latest_json})"] = json.loads(latest_json.read_text(encoding="utf-8")).get("version")
    wrong = [f"{where} says {got!r}" for where, got in found.items() if got != version]
    if wrong:
        raise VersionError(f"VERSION is {version}, but " + "; ".join(wrong))
    return version


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("agree")
    a.add_argument("--root", type=Path, default=Path("."))
    a.add_argument("--info-plist", type=Path)
    a.add_argument("--latest-json", type=Path)
    p = sub.add_parser("plan")
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "agree":
            version = agree(args.root, args.info_plist, args.latest_json)
            print(f"✓ every version stamp says {version}", file=sys.stderr)
            return 0
        version = _read(args.root, "VERSION").strip()
        result = plan(version, parse_tags(sys.stdin.read()), dry_run=args.dry_run)
    except VersionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"version={result.version}")
    print(f"status={result.status}")
    print(f"latest={'true' if result.latest else 'false'}")
    print(f"previous={result.previous}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
