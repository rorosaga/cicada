#!/usr/bin/env python3
"""logo-freshness.py — is each bundled brand mark still the one its vendor serves? A report, never a change.

The curated set (`app/assets/logo-set/`, origin `set` in `logos.manifest.json`, G217) is frozen on the day each source
was fetched: an upstream redraw can never walk into the app, which is the point (`scripts/fetch-logos.sh`, R-L2). The
cost is that nobody notices a rebrand. This script asks each mark's own `source_url` once and compares the bytes it
gets with the committed source's sha256:

- `same`      — the vendor still serves exactly the committed file;
- `changed`   — it serves something else: a redraw, a re-export, or only whitespace. A maintainer looks at it (the
                fetched bytes are kept under `--save-dir` for that) and, if it is a real rebrand, replaces the source
                in a reviewed commit and rebuilds with `scripts/fetch-logos.sh`;
- `pinned`    — the URL names an immutable revision (a 40-hex commit, an npm version, a Commons file page): asking it
                says nothing about the vendor's current mark, so it is not asked;
- `unreachable` — no answer, a refusal, a redirect off https, or more than the cap. Never retried with other headers.

It never edits the repo, never commits, never opens a pull request: `.github/workflows/logo-freshness.yml` runs it on a
schedule and prints the table into the job summary, and a person decides. The fetch is asset work for a maintainer,
not a Cicada runtime path (none of the product's network gates is read): 4 s a request, at most 1 MiB, no cookies,
https only, at most 3 redirects, each still https.

Usage:
  scripts/logo-freshness.py                      the table on stdout (markdown)
  scripts/logo-freshness.py --json               one JSON object instead
  scripts/logo-freshness.py --save-dir DIR       keep each changed file as DIR/<slug>.<ext> for review
  scripts/logo-freshness.py --only SLUG          one mark
  scripts/logo-freshness.py --strict             exit 1 when any mark changed (a local check; CI never uses it)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

REPO = Path(__file__).resolve().parents[1]
SET_DIR = REPO / "app" / "assets" / "logo-set"
TIMEOUT_S = 4.0
MAX_BYTES = 1024 * 1024
MAX_REDIRECTS = 3
USER_AGENT = "Mozilla/5.0 (CicadaLogoFreshness; +https://github.com/rorosaga/cicada)"

SAME, CHANGED, PINNED, UNREACHABLE = "same", "changed", "pinned", "unreachable"
#: A URL that names one immutable revision: a git commit, a versioned npm package, a Commons file page.
_PINNED = (re.compile(r"/[0-9a-f]{40}/"), re.compile(r"@\d+\.\d+\.\d+/"), re.compile(r"commons\.wikimedia\.org/wiki/File:"))


def is_pinned(url: str) -> bool:
    return any(p.search(url) for p in _PINNED)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # every hop is followed (and checked) by `fetch`
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(url: str, *, opener=None) -> tuple[bytes | None, str]:
    """``(bytes, "")`` or ``(None, why)``. https on every hop, the cap read and no more, no cookie jar at all."""
    opener = opener or _OPENER
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if urlparse(current).scheme != "https":
            return None, "not https"
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        try:
            with opener.open(request, timeout=TIMEOUT_S) as resp:
                body = resp.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    return None, "over 1 MiB"
                return body, ""
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
            if location:
                current = urljoin(current, location)
                continue
            return None, f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return None, type(exc).__name__
    return None, "too many redirects"


#: Adam7's seven passes: (x start, y start, x step, y step).
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def _unfilter(raw: bytes, offset: int, width: int, height: int, channels: int) -> tuple[list[bytearray], int] | None:
    """One (sub)image's scanlines with PNG's five filters undone, and where the next one starts."""
    stride = width * channels
    if offset + height * (stride + 1) > len(raw):
        return None
    rows, prev = [], bytearray(stride)
    for _ in range(height):
        kind, line = raw[offset], bytearray(raw[offset + 1:offset + 1 + stride])
        offset += stride + 1
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up, corner = prev[i], (prev[i - channels] if i >= channels else 0)
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        rows.append(line)
        prev = line
    return rows, offset


def png_rgba(data: bytes) -> tuple[int, int, bytes] | None:
    """``(width, height, RGBA bytes)`` of an 8-bit PNG (grey, RGB, palette, grey+alpha or RGBA; plain or Adam7) — the
    shapes vendor icons ship in — else None. Pure standard library: a CDN that re-compresses the same icon (or
    re-saves it interlaced) is not a rebrand, and only the pixels can say so."""
    import struct
    import zlib

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, palette, trns = 8, [], b"", b""
    width = height = depth = ctype = interlace = None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            trns = chunk
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if width is None or depth != 8 or interlace not in (0, 1) or channels is None or width * height > 4096 * 4096:
        return None
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None

    def rgba(px) -> bytes:
        if ctype == 6:
            return bytes(px)
        if ctype == 2:
            return bytes(px) + b"\xff"
        if ctype == 0:
            return bytes((px[0], px[0], px[0], 255))
        if ctype == 4:
            return bytes((px[0], px[0], px[0], px[1]))
        i = px[0]
        return (palette[i * 3:i * 3 + 3] or b"\x00\x00\x00") + bytes((trns[i] if i < len(trns) else 255,))

    out = bytearray(width * height * 4)
    passes = _ADAM7 if interlace else ((0, 0, 1, 1),)
    offset = 0
    for x0, y0, dx, dy in passes:
        pw, ph = (width - x0 + dx - 1) // dx, (height - y0 + dy - 1) // dy
        if pw <= 0 or ph <= 0:
            continue
        got = _unfilter(raw, offset, pw, ph, channels)
        if got is None:
            return None
        rows, offset = got
        for j, line in enumerate(rows):
            y = y0 + j * dy
            for i in range(pw):
                at = (y * width + x0 + i * dx) * 4
                out[at:at + 4] = rgba(line[i * channels:(i + 1) * channels])
    return width, height, bytes(out)


#: Mean absolute difference per RGBA channel (0–255) under which two rasters are the same picture re-encoded.
SAME_PIXELS = 2.0


def pixel_distance(a: bytes, b: bytes) -> float | None:
    """How far apart two PNGs' pixels are (mean absolute difference per channel), or None when either cannot be
    decoded or they differ in size (a different size is a different file, whatever it shows)."""
    pa, pb = png_rgba(a), png_rgba(b)
    if pa is None or pb is None or pa[:2] != pb[:2]:
        return None
    return sum(abs(x - y) for x, y in zip(pa[2], pb[2])) / len(pa[2])


def _ext(body: bytes) -> str:
    if body.startswith(b"\x89PNG"):
        return "png"
    if body[:3] == b"\xff\xd8\xff":
        return "jpg"
    if body[:4] == b"\x00\x00\x01\x00":
        return "ico"
    return "svg" if b"<svg" in body[:2048].lower() else "bin"


def check(set_dir: Path = SET_DIR, *, only: str | None = None, fetcher=fetch, save_dir: Path | None = None) -> dict:
    manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for logo in manifest["logos"]:
        slug, url = logo["slug"], logo["source_url"]
        if only and slug != only:
            continue
        source = (set_dir / logo["file"]).read_bytes()
        committed = hashlib.sha256(source).hexdigest()
        row = {"slug": slug, "url": url, "fetched": logo.get("fetched"), "format": logo.get("format"),
               "pixels": logo.get("pixels"), "tier": logo.get("source_tier")}
        if is_pinned(url):
            rows.append({**row, "state": PINNED})
            continue
        body, why = fetcher(url)
        if body is None:
            rows.append({**row, "state": UNREACHABLE, "why": why})
            continue
        now = hashlib.sha256(body).hexdigest()
        if now == committed:
            rows.append({**row, "state": SAME})
            continue
        distance = pixel_distance(source, body)
        if distance is not None and distance < SAME_PIXELS:
            rows.append({**row, "state": SAME, "why": "re-encoded, same pixels"})
            continue
        ext = _ext(body)
        if save_dir is not None:
            save_dir.mkdir(parents=True, exist_ok=True)
            (save_dir / f"{slug}.{ext}").write_bytes(body)
        rows.append({**row, "state": CHANGED, "served": ext, "bytes": len(body), "sha256": now,
                     **({"pixel_distance": round(distance, 1)} if distance is not None else {})})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {"set_generated": manifest.get("generated"), "counts": counts, "rows": rows}


def markdown(report: dict) -> str:
    counts = ", ".join(f"{k} {v}" for k, v in sorted(report["counts"].items())) or "nothing checked"
    lines = [f"Logo freshness against the set of {report.get('set_generated') or 'unknown date'}: {counts}.", "",
             "| mark | state | fetched | source | note |", "|---|---|---|---|---|"]
    order = {CHANGED: 0, UNREACHABLE: 1, SAME: 2, PINNED: 3}
    for r in sorted(report["rows"], key=lambda r: (order[r["state"]], r["slug"])):
        note = r.get("why") or ""
        if r["state"] == CHANGED:
            note = f"now serves {r['served']}, {r['bytes']} bytes" + (
                f", pixels {r['pixel_distance']} apart" if "pixel_distance" in r else "")
        lines.append(f"| `{r['slug']}` | {r['state']} | {r.get('fetched') or ''} | {r.get('tier') or ''} | {note} |")
    lines += ["", "A `changed` mark is for a person to look at: nothing here edits the set or opens a pull request."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only")
    parser.add_argument("--save-dir", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    report = check(only=args.only, save_dir=args.save_dir)
    print(json.dumps(report, indent=2) if args.json else markdown(report))
    return 1 if args.strict and report["counts"].get(CHANGED) else 0


if __name__ == "__main__":
    sys.exit(main())
