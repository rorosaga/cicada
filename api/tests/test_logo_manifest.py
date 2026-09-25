"""T6 (R-L7) — the committed brand marks are the ones the manifest claims.

No network: this test proves only that `Resources/logos/` and
`logos.manifest.json` and `LOGOS.md` agree. The fetch itself is
`scripts/fetch-logos.sh`, run by hand on a maintainer's Mac (R-L2), because a
vendor mark that changed upstream must never land unreviewed — and because the
app must add no runtime network path to show a logo.

A hand-edited PNG, an asset committed without an attribution row, or an
attribution row whose licence no longer matches the manifest all fail here.
"""

import hashlib
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOGOS = _REPO_ROOT / "app/CicadaApp/Sources/CicadaApp/Resources/logos"
_MANIFEST = _LOGOS / "logos.manifest.json"
_ATTRIBUTION = _LOGOS / "LOGOS.md"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_committed_png_has_a_manifest_entry_and_vice_versa():
    """R1 — the manifest describes exactly what is committed, and nothing else."""
    declared = {a["file"] for a in _manifest()["assets"]}
    committed = {p.name for p in _LOGOS.glob("*.png")}
    assert declared == committed, (
        f"undeclared: {sorted(committed - declared)}; missing file: {sorted(declared - committed)}"
    )


def test_every_committed_png_matches_its_recorded_sha256():
    for asset in _manifest()["assets"]:
        path = _LOGOS / asset["file"]
        assert _sha256(path) == asset["sha256"], (
            f"{asset['file']} changed without re-running scripts/fetch-logos.sh"
        )


def test_attribution_table_names_every_asset_with_the_same_licence():
    """LOGOS.md is the repo's NOTICE for third-party marks — the repo has a
    LICENSE but nothing else covering vendor art."""
    text = _ATTRIBUTION.read_text(encoding="utf-8")
    for asset in _manifest()["assets"]:
        assert f"`{asset['id']}`" in text, f"{asset['id']} has no attribution row"
        assert asset["licence"] in text, f"{asset['id']}'s licence line is not in LOGOS.md"


def test_ids_are_unique_and_dark_siblings_declare_their_base():
    """R4 — a `-dark` file is a variant of a base mark, never a standalone one."""
    assets = _manifest()["assets"]
    ids = [a["id"] for a in assets]
    assert len(ids) == len(set(ids))
    for ident in ids:
        if ident.endswith("-dark"):
            assert ident[: -len("-dark")] in ids, f"{ident} has no base mark"


def test_the_manifest_records_a_licence_and_a_restriction_for_every_asset():
    for asset in _manifest()["assets"]:
        assert asset["licence"].strip(), asset["id"]
        assert asset["restrictions"].strip(), asset["id"]
        assert asset["origin"] in {"commons", "repo", "recut", "legacy"}, asset["id"]


def test_a_repo_mark_is_pinned_to_a_commit_on_the_vendor_s_own_repository():
    """R-AG9 — a vendor-repo mark is fetched from one immutable commit, never a
    branch, and carries the same upstream-drift guard (`svgSha256`) a Commons
    mark does: a redraw on the vendor's `main` must never reach the app unreviewed."""
    import re

    pinned = re.compile(r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+\.svg$")
    repo_assets = [a for a in _manifest()["assets"] if a["origin"] == "repo"]
    assert {a["id"] for a in repo_assets} == {"opencode", "opencode-dark", "openrouter"}
    for asset in repo_assets:
        assert pinned.match(asset["sourceUrl"]), asset["id"]
        assert re.fullmatch(r"[0-9a-f]{64}", asset.get("svgSha256", "")), asset["id"]


def test_the_two_identical_claude_rasters_are_retired():
    """R-AG8 — Claude Code is the Claude mark plus an app-drawn badge; the two
    byte-identical legacy rasters are unlicensed dead bytes once nothing draws them."""
    ids = {a["id"] for a in _manifest()["assets"]}
    assert not ids & {"claude-code", "claude-desktop"}
