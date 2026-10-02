"""G138/G166 — `scripts/verify-skills.sh --print-urls` builds each pinned SKILL.md's raw URL with a real
join: `path` may be "" (browser-harness keeps its SKILL.md at the repo root), and the old f-string
produced `.../<sha>//SKILL.md`, which GitHub answers with a 307. Offline: no network is touched."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import skill_catalog

ROOT = Path(__file__).resolve().parents[2]


def _urls() -> list[str]:
    out = subprocess.run(["bash", str(ROOT / "scripts" / "verify-skills.sh"), "--print-urls"],
                         capture_output=True, text=True, check=True, cwd=ROOT).stdout
    return [line for line in out.splitlines() if line.strip()]


def test_print_urls_builds_a_clean_join_for_a_root_and_a_subpath_skill():
    urls = _urls()
    assert all("//" not in u.split("https://", 1)[1] for u in urls), urls
    root = next(u for u in urls if "browser-harness" in u)
    assert root == ("https://raw.githubusercontent.com/browser-use/browser-harness/"
                    "c24e5072ee66f8499bacd663f4f4bcb089bc4492/SKILL.md")
    sub = next(u for u in urls if "macos-harness" in u)
    assert sub == ("https://raw.githubusercontent.com/browser-use/macos-harness/"
                   "b88e4d77403bbcac35752eef4f4dd72db3663fd6/skills/macos-harness/SKILL.md")
    assert all(u.endswith("/SKILL.md") for u in urls)


def test_every_pin_with_a_hash_has_a_url():
    pinned = [s for s in skill_catalog.load()["skills"] if (s.get("pin") or {}).get("skillMdSha256")]
    assert len(_urls()) == len(pinned)
