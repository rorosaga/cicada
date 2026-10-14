"""2026-10-14 — a ref typed in another case resolves to the page's own id, on a case-insensitive filesystem too.

macOS's filesystem ignores case when it looks a name up, so `entities/Alpha-Project.md` "exists" when the page is
`entities/alpha-project.md`. The resolver handed back the typed spelling, and every caller that takes the stem as the
page's id then knew no page by it: `cicada_note_progress(project="<Name>")` answered "<Name> is a page; name the
project it belongs to" about a project. Synthetic bank only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _synthetic_bank import _bank
from api.services import backlog, id_utils, mcp_tools, project_timeline
from api.services.entity_sources import gather_entity_sources


def _case_insensitive(directory: Path) -> bool:
    probe = directory / "case-probe.md"
    probe.write_text("x", encoding="utf-8")
    try:
        return (directory / "CASE-PROBE.md").exists()
    finally:
        probe.unlink()


def _ctx(bank: Path):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")


def test_on_disk_spells_a_path_as_its_directory_does(tmp_path):
    """Pure listing logic — runs on any filesystem: the exact name when it is there, else the one entry equal to it
    ignoring case and Unicode normalization, else the path as given."""
    (tmp_path / "alpha-project.md").write_text("x", encoding="utf-8")
    (tmp_path / "atlético.md").write_text("x", encoding="utf-8")   # NFC on disk
    assert id_utils.on_disk(tmp_path / "Alpha-Project.md") == tmp_path / "alpha-project.md"
    assert id_utils.on_disk(tmp_path / "alpha-project.md") == tmp_path / "alpha-project.md"
    assert id_utils.on_disk(tmp_path / "ATLÉTICO.md").name in ("atlético.md", "atlético.md")
    assert id_utils.on_disk(tmp_path / "missing.md") == tmp_path / "missing.md"
    assert id_utils.on_disk(tmp_path / "nowhere" / "x.md") == tmp_path / "nowhere" / "x.md"


def test_a_new_page_is_seen_after_the_listing_was_cached(tmp_path):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    assert id_utils.on_disk(tmp_path / "A.md").name == "a.md"
    import os
    (tmp_path / "b.md").write_text("x", encoding="utf-8")
    os.utime(tmp_path, ns=(1, os.stat(tmp_path).st_mtime_ns + 1_000_000))
    assert id_utils.on_disk(tmp_path / "B.md").name == "b.md"


def test_the_resolver_and_every_ref_reader_give_the_pages_own_id(tmp_path):
    bank = _bank(tmp_path)
    if not _case_insensitive(bank / "entities"):
        pytest.skip("case-sensitive filesystem: 'Alpha-Project.md' cannot exist here, so the typed spelling never "
                    "reached the stem — the listing logic is covered by test_on_disk_spells_a_path_as_its_directory_does")
    page = id_utils.resolve_entity_file(bank, "Alpha-Project")
    assert page is not None and page.name == "alpha-project.md"
    assert project_timeline._Bank(bank, None).type_of(page.stem) == "project"

    out = mcp_tools.note_progress(_ctx(bank), "Alpha-Project", "happened", "Shipped the alpha-project index", "done")
    assert "is a page" not in out and "name the project" not in out, out

    stem, fm = backlog.project_page(bank, "Alpha-Project")
    assert (stem, fm.get("type")) == ("alpha-project", "project")
    assert gather_entity_sources(bank, "Alpha-Project")["entity_id"] == "alpha-project"
    detail = mcp_tools.recall_detail(_ctx(bank), "Alpha-Project")
    assert "Alpha-Project" not in str(detail), "recall_detail names the page by its own id"
