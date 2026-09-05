#!/usr/bin/env bash
#
# fetch-logos.sh — the maintainer pipeline for the brand marks the app draws.
#
# WHAT THIS IS (R-L2). A tool a maintainer runs by hand on a Mac, once, when a
# mark is added or an upstream file changes. The PNGs it produces are COMMITTED.
# It is not a Cicada capture path and not a runtime code path: the app never
# fetches a logo, so none of the three outbound gates
# (CICADA_ALLOW_CONNECTOR_FETCH, CICADA_ALLOW_FEED_FETCH, CICADA_ALLOW_LOGO_FETCH)
# is read, written or involved here. Those gate the *product*; this is asset work.
#
# WHY BY HAND AND NOT NIGHTLY. A vendor mark that changed upstream must never
# land unreviewed — a redraw, a rebrand or a vandalised Commons file would
# otherwise walk straight into the app. So drift stops the run and asks
# (see --accept), and every regenerated PNG is opened and eyeballed before it is
# committed (R10 / R-L8): NSImage reports success on an SVG whose clip path it
# silently dropped, which is exactly how a wrong-looking mark gets shipped.
#
# NOMINATIVE USE. A vendor mark identifies the vendor's product and nothing
# else. It is never restyled, recoloured, cropped or combined with Cicada's own
# marks. The one permitted transform is `tools/monoflip.swift` (R4), an exact
# luminance inversion of a mark that has no hue, and it refuses colour.
#
# USAGE
#   scripts/fetch-logos.sh                 fetch/verify everything, rewrite the ledger
#   scripts/fetch-logos.sh --check         offline, read-only: do the bytes match the ledger?
#   scripts/fetch-logos.sh --accept        record upstream drift instead of failing on it
#   scripts/fetch-logos.sh --only <id>     restrict a real run to one manifest id
#
# The ledger is `logos.manifest.json` (one entry per committed file, R1) and
# `LOGOS.md` (the attribution table — this repo's NOTICE for third-party art).
# `api/tests/test_logo_manifest.py` (T6) holds the three of them to each other.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"   # portability: no author-machine path, ever
LOGOS="$REPO/app/CicadaApp/Sources/CicadaApp/Resources/logos"
MANIFEST="$LOGOS/logos.manifest.json"
ATTRIBUTION="$LOGOS/LOGOS.md"

# The repo's venv, not the system python: `jq` is not guaranteed on a Mac, the
# venv is (it is what `api/` runs on). Nothing here imports Cicada code.
PY="$REPO/api/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || { echo "no python3 available (tried $REPO/api/.venv/bin/python)" >&2; exit 2; }

MODE="run"
ACCEPT=0
ONLY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)  MODE="check"; shift ;;
        --accept) ACCEPT=1; shift ;;
        --only)   ONLY="${2:-}"; [[ -n "$ONLY" ]] || { echo "--only needs an id" >&2; exit 2; }; shift 2 ;;
        -h|--help) sed -n '3,30p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
    esac
done

[[ -f "$MANIFEST" ]] || { echo "no manifest at $MANIFEST" >&2; exit 2; }

# --- read-only queries over the manifest (python, never jq) -------------------

manifest_get() {  # manifest_get <top-level key> <fallback>
    "$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2]) or sys.argv[3])' \
        "$MANIFEST" "$1" "$2"
}

# One row per asset, unit-separator delimited. NOT tab: tab is an IFS-whitespace
# character, so bash collapses a run of them and an asset with no `commonsFile`
# and no `svgSha256` would have its `sha256` read into the wrong variable — which
# silently disables the drift guard below (found by running it).
manifest_rows() {  # id US file US origin US commonsFile US svgSha256 US sha256
    "$PY" -c '
import json, sys
for a in sorted(json.load(open(sys.argv[1]))["assets"], key=lambda a: a["id"]):
    print("\x1f".join(str(a.get(k) or "") for k in
          ("id", "file", "origin", "commonsFile", "svgSha256", "sha256")))
' "$MANIFEST"
}

sha256_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

# --- --check: offline, read-only (this is what a CI job would run) ------------
#
# It answers "are the committed bytes the ones the ledger claims" and nothing
# else. Upstream drift is a different question, it needs the network, and it is
# only asked on a real run (see the svgSha256 comparison below).
if [[ "$MODE" == "check" ]]; then
    "$PY" - "$LOGOS" "$MANIFEST" "$ATTRIBUTION" <<'PYCHECK'
import hashlib, json, sys
from pathlib import Path

logos, manifest_path, attribution_path = (Path(p) for p in sys.argv[1:4])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
attribution = attribution_path.read_text(encoding="utf-8")
problems = []

declared = {a["file"] for a in manifest["assets"]}
committed = {p.name for p in logos.glob("*.png")}
for name in sorted(committed - declared):
    problems.append(f"{name}: committed but not in the manifest (R1)")
for name in sorted(declared - committed):
    problems.append(f"{name}: in the manifest but not committed (R1)")

for asset in manifest["assets"]:
    path = logos / asset["file"]
    if not path.exists():
        continue
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != asset.get("sha256"):
        problems.append(f"{asset['file']}: sha256 {actual[:12]} != recorded "
                        f"{str(asset.get('sha256'))[:12]} — edited by hand?")
    if f"`{asset['id']}`" not in attribution:
        problems.append(f"{asset['id']}: no row in LOGOS.md")
    elif asset["licence"] not in attribution:
        problems.append(f"{asset['id']}: LOGOS.md does not carry its recorded licence")

for line in problems:
    print(f"FAIL {line}")
print(f"checked {len(manifest['assets'])} assets against {logos}")
sys.exit(1 if problems else 0)
PYCHECK
    exit 0
fi

# --- a real run ---------------------------------------------------------------

UA="$(manifest_get userAgent 'CicadaLogoFetch/1.0 (+https://github.com/rorosaga/cicada)')"
SIZE="$(manifest_get size 256)"

# Two directories on purpose. The scratch dir is per-run and trapped; the tool
# cache is stable so a second run in the same session skips three ~1.6 s
# `swiftc` builds when the sources have not changed.
WORK="${TMPDIR:-/tmp}/cicada-logos.$$"
TOOLBIN="${TMPDIR:-/tmp}/cicada-logos-tools"
mkdir -p "$WORK/meta" "$TOOLBIN"
trap 'rm -rf "$WORK"' EXIT

ensure_tool() {  # built lazily: an all-legacy run needs no rasterizer at all
    local name="$1" src="$REPO/tools/$1.swift" bin="$TOOLBIN/$1"
    if [[ ! -x "$bin" || "$src" -nt "$bin" ]]; then
        echo "  building tools/$name.swift" >&2
        swiftc -O -o "$bin" "$src"
    fi
    echo "$bin"
}

WRITTEN=()
FAILED=0

fetch_commons() {  # fetch_commons <id> <file> <commonsFile> <recorded svg sha>
    local id="$1" file="$2" commons="$3" recorded="$4"
    local encoded svg
    encoded="$("$PY" -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1].replace(" ","_"),safe=""))' "$commons")"
    svg="$WORK/$id.svg"

    # A descriptive User-Agent is not optional: Wikimedia answers an empty one
    # with 403 and a descriptive one with 200 (both measured 2026-09-05), and
    # its UA policy asks for a contact URL. The URL is the project's public
    # repo — already in README.md — not personal data.
    if ! curl -sSL --fail -A "$UA" -o "$svg" \
        "https://commons.wikimedia.org/wiki/Special:FilePath/$encoded"; then
        echo "FAIL $id: could not fetch Special:FilePath/$commons" >&2
        FAILED=1
        return 0
    fi

    local actual
    actual="$(sha256_of "$svg")"
    if [[ -n "$recorded" && "$actual" != "$recorded" ]]; then
        echo "DRIFT $id: upstream sha $recorded → $actual" >&2
        if [[ "$ACCEPT" -eq 0 ]]; then
            echo "  refusing to overwrite a reviewed mark; re-run with --accept once you have looked at it" >&2
            FAILED=1
            return 0
        fi
    elif [[ -n "$recorded" ]]; then
        # Unchanged upstream: leave the committed PNG exactly as it is, so a
        # re-run leaves `git status` clean.
        echo "  $id: upstream unchanged" >&2
        return 0
    fi

    # Licence, artist and restrictions are RECORDED here and never re-derived at
    # runtime — the app ships an attribution table, not an API client.
    curl -sSL --fail -A "$UA" -o "$WORK/$id.info.json" \
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url%7Cextmetadata%7Csha1%7Csize&titles=File%3A$encoded" \
        || echo "  $id: imageinfo unavailable; licence fields left as recorded" >&2

    "$PY" - "$WORK/$id.info.json" "$WORK/meta/$id.json" "$actual" "$commons" <<'PYMETA'
import html, json, re, sys
from pathlib import Path

info_path, out_path, svg_sha, commons_file = sys.argv[1:5]
meta = {"svgSha256": svg_sha,
        "sourceUrl": "https://commons.wikimedia.org/wiki/File:" + commons_file.replace(" ", "_")}
try:
    pages = json.loads(Path(info_path).read_text(encoding="utf-8"))["query"]["pages"]
    extra = list(pages.values())[0]["imageinfo"][0].get("extmetadata", {})
except Exception:
    extra = {}


def _plain(key: str) -> str:
    """Commons returns HTML in extmetadata; the manifest stores prose."""
    raw = (extra.get(key) or {}).get("value") or ""
    return html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip().replace("\n", " ")


if _plain("LicenseShortName"):
    meta["licence"] = _plain("LicenseShortName")
if _plain("Artist"):
    meta["artist"] = re.sub(r"\s{2,}", " ", _plain("Artist"))
if _plain("Restrictions"):
    # Commons' own machine-readable restriction tags (trademarked, insignia, …)
    # are appended to Cicada's standing nominative-use line, never replace it.
    meta["commonsRestrictions"] = _plain("Restrictions")
Path(out_path).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
PYMETA

    # rsvg-convert when a maintainer happens to have it; otherwise the AppKit
    # rasterizer, which is what a stock Mac actually has (measured: rsvg-convert,
    # ImageMagick, Inkscape and cairosvg all absent; `qlmanage -t` hung > 120 s).
    local png="$LOGOS/$file"
    if command -v rsvg-convert >/dev/null 2>&1; then
        rsvg-convert -w "$SIZE" -h "$SIZE" -o "$png" "$svg"
    else
        "$(ensure_tool svg2png)" "$svg" "$png" "$SIZE"
    fi

    if ! verify_png "$png" "$id"; then
        FAILED=1
        return 0
    fi
    WRITTEN+=("$png")
}

verify_png() {  # geometry and alpha, straight from sips — no PNG parser here
    local png="$1" id="$2" w h alpha
    w="$(sips -g pixelWidth "$png" | awk '/pixelWidth/{print $2}')"
    h="$(sips -g pixelHeight "$png" | awk '/pixelHeight/{print $2}')"
    alpha="$(sips -g hasAlpha "$png" | awk '/hasAlpha/{print $2}')"
    if [[ "$alpha" != "yes" ]]; then
        echo "FAIL $id: no alpha channel — an opaque square inside a rounded card" >&2
        return 1
    fi
    if [[ "$w" != "$h" ]]; then
        echo "FAIL $id: ${w}x${h} is not square" >&2
        return 1
    fi
    if [[ "$w" -lt "$SIZE" ]]; then
        echo "FAIL $id: ${w}px is below the manifest's floor of ${SIZE}px" >&2
        return 1
    fi
    return 0
}

while IFS=$'\x1f' read -r id file origin commons svg_sha sha; do
    [[ -n "$id" ]] || continue
    if [[ -n "$ONLY" && "$ONLY" != "$id" ]]; then continue; fi
    # The ledger rewrite below re-records a sha only for an id this loop
    # verified. Without that, `--only <id>` would quietly re-bless a hand-edited
    # PNG it never looked at — the opposite of what the guard is for.
    echo "$id" >> "$WORK/processed.txt"
    case "$origin" in
        commons)
            fetch_commons "$id" "$file" "$commons" "$svg_sha"
            ;;
        recut|legacy)
            # Never fetched, never regenerated — only the sha is verified.
            # A recut is a one-time act (R5): the committed file already carries
            # alpha, and `alphakey` exits 3 on it by design, so a pipeline that
            # tried to re-run the recut would fail on every run. `derivedFrom`
            # records the source blob and the exact invocations instead, which
            # is what makes it reproducible by hand and reviewable.
            if [[ ! -f "$LOGOS/$file" ]]; then
                echo "FAIL $id: $file is in the manifest but not committed (R1)" >&2
                FAILED=1
                continue
            fi
            actual="$(sha256_of "$LOGOS/$file")"
            if [[ -z "$sha" ]]; then
                echo "  $id: seeding sha256" >&2
            elif [[ "$actual" != "$sha" ]]; then
                echo "DRIFT $id: committed sha $sha → $actual" >&2
                if [[ "$ACCEPT" -eq 0 ]]; then
                    echo "  a $origin asset changed without the pipeline; re-run with --accept to re-bless it" >&2
                    FAILED=1
                fi
            fi
            ;;
        *)
            echo "FAIL $id: unknown origin '$origin' (commons|recut|legacy)" >&2
            FAILED=1
            ;;
    esac
done < <(manifest_rows)

if [[ "$FAILED" -ne 0 ]]; then
    echo "run failed; the manifest and LOGOS.md were left untouched" >&2
    exit 1
fi

# --- rewrite the ledger -------------------------------------------------------
#
# sha256s come from the files on disk (every one of them has just been fetched,
# verified or explicitly re-blessed above), assets sort by id, and LOGOS.md is a
# pure function of the manifest — so a no-op run is a no-op diff.
touch "$WORK/processed.txt"
"$PY" - "$LOGOS" "$MANIFEST" "$ATTRIBUTION" "$WORK/meta" "$WORK/processed.txt" <<'PYWRITE'
import hashlib, json, sys
from pathlib import Path

logos, manifest_path, attribution_path, meta_dir, processed_path = (
    Path(p) for p in sys.argv[1:6])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
processed = set(processed_path.read_text(encoding="utf-8").split())

for asset in manifest["assets"]:
    meta_file = meta_dir / f"{asset['id']}.json"
    if meta_file.exists():
        asset.update(json.loads(meta_file.read_text(encoding="utf-8")))
    path = logos / asset["file"]
    if asset["id"] in processed and path.exists():
        asset["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

manifest["assets"].sort(key=lambda a: a["id"])
manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

ROWS = ("id", "file", "origin", "source", "licence", "restrictions")
lines = [
    "# Third-party brand marks",
    "",
    "**Generated by `scripts/fetch-logos.sh` — do not edit by hand.**",
    "The manifest beside it (`logos.manifest.json`) is the machine-readable half;",
    "`api/tests/test_logo_manifest.py` holds the two of them to the committed bytes.",
    "",
    "Every mark below identifies the product it names and is used nominatively:",
    "Cicada does not restyle, recolour, crop or combine them, and claims no",
    "affiliation with, sponsorship by, or endorsement from their owners. A `-dark`",
    "row is an exact luminance inversion of a mark that has no hue (R4) — the one",
    "transform applied to any of them. Owners: to have a mark removed or replaced,",
    "open an issue on the repository.",
    "",
    "A `legacy` row predates this ledger: it was committed before the pipeline",
    "existed, so its provenance is the commit that introduced it rather than an",
    "upstream URL, and its licence line says exactly that instead of inventing one.",
    "",
    "| id | file | origin | source | licence | restrictions |",
    "|---|---|---|---|---|---|",
]
for asset in manifest["assets"]:
    source = asset.get("sourceUrl") or "—"
    if asset.get("commonsFile"):
        source = f"[{asset['commonsFile']}]({source})" if source else asset["commonsFile"]
    elif asset.get("derivedFrom"):
        source = f"derived: {asset['derivedFrom']}"
    artist = asset.get("artist")
    licence = asset["licence"] + (f" — {artist}" if artist else "")
    restrictions = asset["restrictions"]
    if asset.get("commonsRestrictions"):
        restrictions += f" (Commons: {asset['commonsRestrictions']})"
    cells = [f"`{asset['id']}`", asset["file"], asset["origin"], source, licence, restrictions]
    lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
lines += [
    "",
    f"{len(manifest['assets'])} marks. New ones are rasterized at "
    f"{manifest.get('size', 256)} px; the 2026-08-31 favicon rasters stay at 128 px",
    "because upscaling a favicon would be fake resolution.",
    "",
]
attribution_path.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {manifest_path.name} and {attribution_path.name} ({len(manifest['assets'])} assets)")
PYWRITE

if [[ ${#WRITTEN[@]} -gt 0 ]]; then
    printf '%s\n' "${WRITTEN[@]}"
    echo "open each one before committing (R-L8)"
else
    echo "no PNG was rewritten"
fi
