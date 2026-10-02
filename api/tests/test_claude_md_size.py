"""CLAUDE.md stays the rails, not the manual (2026-10-01).

CLAUDE.md is loaded into every agent session. It had grown to 203,000 characters — past Claude Code's 150,000-character
warning — because every feature PR added its implementation detail there. The detail moved word for word to
``docs/architecture/``; CLAUDE.md keeps the mission, the working rules, every rail in short form and a map of the area
docs. A PR updates the area doc its change makes wrong and touches CLAUDE.md only when a rail changes.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = ROOT / "CLAUDE.md"
LIMIT = 60_000


def test_claude_md_stays_under_the_limit():
    size = len(CLAUDE.read_text(encoding="utf-8"))
    assert size <= LIMIT, (
        f"CLAUDE.md is {size:,} characters (limit {LIMIT:,}). Move detail to its docs/architecture/ file and keep only "
        "the rail here."
    )


def test_every_architecture_doc_it_links_exists_and_is_linked():
    text = CLAUDE.read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\((docs/architecture/[\w.-]+\.md)\)", text))
    assert linked, "CLAUDE.md must map the area docs"
    for rel in linked:
        assert (ROOT / rel).is_file(), f"CLAUDE.md links {rel}, which does not exist"
    on_disk = {f"docs/architecture/{p.name}" for p in (ROOT / "docs/architecture").glob("*.md")}
    assert on_disk <= linked, f"area docs CLAUDE.md does not map: {sorted(on_disk - linked)}"
