#!/usr/bin/env python3
"""Write a release's `latest.json` (G182) — what the in-app updater reads.

    latest_json.py --version 0.3.0 --build 1530 --zip dist/Cicada-0.3.0.zip \
        --signature <base64> --repo-url https://github.com/<owner>/<repo>

The URL is the asset's download address under the version's tag, so the file
stays correct even after a newer release becomes "latest". Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def build(version: str, build_number: str, zip_path: Path, signature: str, repo_url: str) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"not a release version: {version}")
    if not build_number.isdigit():
        raise ValueError(f"not a build number: {build_number}")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    tag = f"v{version}"
    base = repo_url.rstrip("/")
    return {
        "version": version,
        "build": int(build_number),
        "url": f"{base}/releases/download/{tag}/{zip_path.name}",
        "size": zip_path.stat().st_size,
        "sha256": digest,
        "signature": signature.strip(),
        "notes_url": f"{base}/releases/tag/{tag}",
        "minimum_macos": "14.0",
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--build", required=True)
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--signature", required=True)
    ap.add_argument("--repo-url", required=True)
    a = ap.parse_args(argv)
    json.dump(build(a.version, a.build, a.zip, a.signature, a.repo_url), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
