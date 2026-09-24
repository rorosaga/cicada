#!/usr/bin/env python3
"""Generate the app's time zone → coordinates table (round-4 D4, G144).

The Home painting follows sunrise and sunset in the Mac's time zone, with no
location permission: SceneClock needs one point per zone, and IANA's tz
database already names one — the zone's principal location.

Provenance: IANA tzdb (https://www.iana.org/time-zones). zone1970.tab and
zone.tab each begin "This file is in the public domain"; the Link lines come
from the same distribution. Order of precedence (R-FA5): zone1970.tab, then
zone.tab (a zone zone1970 folds into another, e.g. Europe/Oslo), then Link
lines resolved to a zone that has a point. Together they cover every
identifier macOS knows but GMT (measured on tzdata 2026d: 442 of 443).

Usage (run it with api/.venv/bin/python — the download path needs tarfile's
"data" extraction filter, Python 3.12 or a late 3.9-3.11 patch release):
  scripts/gen-tz-coordinates.py                   # downloads tzdata-latest.tar.gz
  scripts/gen-tz-coordinates.py --tzdata DIR      # an unpacked tzdata directory
  scripts/gen-tz-coordinates.py --out PATH        # default: the app's resource
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

TZDATA_URL = "https://data.iana.org/time-zones/tzdata-latest.tar.gz"
REGION_FILES = ("africa", "antarctica", "asia", "australasia", "europe", "northamerica",
                "southamerica", "etcetera", "backward", "backzone")
DEFAULT_OUT = (Path(__file__).resolve().parent.parent
               / "app/CicadaApp/Sources/CicadaApp/Resources/scene/tz-coordinates.json")
_ISO6709 = re.compile(r"^([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?$")


def parse_iso6709(value: str) -> tuple[float, float]:
    """±DDMM[SS]±DDDMM[SS] → (latitude, longitude) in decimal degrees."""
    m = _ISO6709.match(value)
    if not m:
        raise ValueError(f"not ISO 6709: {value!r}")
    s1, d1, m1, x1, s2, d2, m2, x2 = m.groups()
    lat = int(d1) + int(m1) / 60 + int(x1 or 0) / 3600
    lon = int(d2) + int(m2) / 60 + int(x2 or 0) / 3600
    return (lat if s1 == "+" else -lat, lon if s2 == "+" else -lon)


def read_tab(path: Path) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        out[cols[2]] = parse_iso6709(cols[1])
    return out


def read_links(tzdata: Path) -> dict[str, str]:
    links: dict[str, str] = {}
    for name in REGION_FILES:
        path = tzdata / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 3 and parts[0] == "Link":
                links.setdefault(parts[2], parts[1])
    return links


def build(tzdata: Path) -> dict[str, list[float]]:
    table = read_tab(tzdata / "zone.tab")
    table.update(read_tab(tzdata / "zone1970.tab"))   # zone1970 wins where both name a zone
    links = read_links(tzdata)
    for alias, target in links.items():
        hops = 0                                       # a link may point at another link; follow up to five
        while target not in table and target in links and hops < 5:
            target, hops = links[target], hops + 1
        if alias not in table and target in table:
            table[alias] = table[target]
    return {zone: [round(lat, 2), round(lon, 2)] for zone, (lat, lon) in sorted(table.items())}


def fetch(dest: Path) -> Path:
    with urllib.request.urlopen(TZDATA_URL, timeout=30) as response:
        data = response.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
    return dest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tzdata", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.tzdata is None:
        import tempfile
        args.tzdata = fetch(Path(tempfile.mkdtemp(prefix="tzdata-")))
    version = (args.tzdata / "version").read_text(encoding="utf-8").strip() if (args.tzdata / "version").exists() else "unknown"
    payload = {"source": "IANA tzdb zone1970.tab + zone.tab + Link lines (public domain); scripts/gen-tz-coordinates.py",
               "version": version, "zones": build(args.tzdata)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['zones'])} zones (tzdata {version}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
