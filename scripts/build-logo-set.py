#!/usr/bin/env python3
"""build-logo-set.py — rasterize the curated logo set (`app/assets/logo-set/`) into the app's bundled PNGs.

Origin `set` in `logos.manifest.json` (G217, 2026-10-22). The set is one mark per provider umbrella, each from the
highest rung of the ladder in `app/assets/logo-set/README.md` (the brand's own site icon → its official GitHub assets
→ lobe-icons → svgl → Commons). The sources are COMMITTED beside this script's input, so a rebuild needs no network
and an upstream redraw can never walk in: replacing a source is a reviewed commit, and `svgSha256` (the source's
sha, SVG or PNG) is the drift guard `fetch-logos.sh --check` and `test_logo_manifest.py` hold.

Called by `scripts/fetch-logos.sh` (a real run) with: <logos dir> <set dir> <svg2png bin> <monoflip bin>.

Three AppKit facts shape the rasterizing, each measured on the 2026-10-22 set:
- NSImage's SVG decoder ignores `<style>`: OpenAI's mark (a `:root { fill }` rule) drew nothing and Tailscale's
  (`#id { fill }` rules) drew one black square. Those rules are inlined as attributes first — the vendor's own light
  colours, nothing invented (`_INLINE`).
- A source with no hue but a near-black fill (`#1C1C24`, `#24292E`) is refused by `monoflip` as coloured, so its
  `-dark` sibling is the vendor's own white mark: the source with its one fill set to `#FFFFFF` (`_WHITE_DARK`).
- A PNG source over 256 px is downsampled with `sips`; one at or under it is copied as served (upscaling would be
  fake resolution — Instinct is 64 px, Warp 196 px, and the app tests exempt them by name).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SIZE = 256

#: `<style>` rules NSImage ignores, written onto the elements they target (the light-scheme values only).
_INLINE = {
    "openai.svg": [(r"<style>.*?</style>", ""), (r'(<svg[^>]*?)\sfill="none"', r'\1 fill="#000"')],
    "tailscale.svg": [
        (r"<style>.*?</style>", ""),
        (r'<g id ="squircle">', '<g id="squircle" fill="#1f1e1e">'),
        (r'<g id ="t">', '<g id="t" fill="#fff">'),
        (r'<g id ="grid">', '<g id="grid" fill="#fff" opacity="0.4">'),
        (r"/\*.*?\*/", ""),
    ],
}

#: Near-black single-fill marks whose `-dark` is the vendor's white mark (monoflip refuses their faint hue).
_WHITE_DARK = {"cline.svg": "#1C1C24", "github.svg": "#24292E"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepared(src: Path, tmp: Path) -> Path:
    rules = _INLINE.get(src.name)
    if not rules:
        return src
    text = src.read_text(encoding="utf-8")
    for pattern, repl in rules:
        text = re.sub(pattern, repl, text, flags=re.S)
    out = tmp / src.name
    out.write_text(text, encoding="utf-8")
    return out


def build(logos: Path, set_dir: Path, svg2png: str, monoflip: str) -> list[dict]:
    manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for logo in manifest["logos"]:
            slug, src = logo["slug"], set_dir / logo["file"]
            out = logos / f"{slug}.png"
            if logo["format"] == "svg":
                subprocess.run([svg2png, str(_prepared(src, tmp)), str(out), str(SIZE)], check=True,
                               capture_output=True)
            elif (logo.get("pixels") or 0) > SIZE:
                subprocess.run(["sips", "-z", str(SIZE), str(SIZE), str(src), "--out", str(out)], check=True,
                               capture_output=True)
            else:
                shutil.copyfile(src, out)
            rows.append(_row(logo, src, out, slug))
            if logo.get("dark_variant"):
                dark = logos / f"{slug}-dark.png"
                if src.name in _WHITE_DARK:
                    white = tmp / f"white-{src.name}"
                    white.write_text(src.read_text(encoding="utf-8").replace(_WHITE_DARK[src.name], "#FFFFFF"),
                                     encoding="utf-8")
                    subprocess.run([svg2png, str(white), str(dark), str(SIZE)], check=True, capture_output=True)
                    how = f"the vendor's white mark: {src.name} with its one fill {_WHITE_DARK[src.name]} → #FFFFFF"
                else:
                    subprocess.run([monoflip, str(out), str(dark)], check=True, capture_output=True)
                    how = f"monoflip {slug}.png {slug}-dark.png"
                rows.append({**_row(logo, src, dark, f"{slug}-dark"), "origin": "recut",
                             "derivedFrom": f"{slug}.png (this manifest) — {how}"})
    return rows


def _row(logo: dict, src: Path, out: Path, ident: str) -> dict:
    return {
        "id": ident,
        "file": out.name,
        "origin": "set",
        "sourceUrl": logo["source_url"],
        "sourceTier": logo["source_tier"],
        "setFile": f"app/assets/logo-set/{src.name}",
        "svgSha256": _sha(src),
        "sha256": _sha(out),
        "umbrella": logo["umbrella"],
        "licence": logo["license"],
        "restrictions": logo["trademark"],
    }


if __name__ == "__main__":
    logos_dir, set_dir, svg2png_bin, monoflip_bin = sys.argv[1:5]
    print(json.dumps(build(Path(logos_dir), Path(set_dir), svg2png_bin, monoflip_bin), indent=2))
