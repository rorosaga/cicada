"""The person-run repair of skill pages left without sources and of references recorded as aliases (G112/G118).

Counts only in the dry run (``--list`` adds what would go); one `cicada` commit on apply; only an alias a Sleep commit
added is ever removed, never one the person recorded; a skill is grounded only on the conversations of the
batch commit that created it AND that a page its text names came up in; the silence clock never moves back; a page
with no batch or no evidence is counted and left alone; never while Sleep runs. Synthetic bank, placeholder names.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from api.scripts import repair_skills_aliases
from api.services import markdown_parser, skill_alias_repair as repair

EP1, EP2, EP3, EP9 = "ep_2026-03-02_1", "ep_2026-03-09_1", "ep_2026-03-10_1", "ep_2026-01-05_1"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=bank, check=True, capture_output=True, text=True).stdout


def _page(bank, stem, fm, body="## Summary\nA thing.\n"):
    markdown_parser.write(bank / "entities" / f"{stem}.md", fm, body)


def _alias(bank, stem, alias):
    path = bank / "entities" / f"{stem}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "aliases": [*(parsed.frontmatter.get("aliases") or []), alias]},
                          parsed.body)


@pytest.fixture
def bank(tmp_path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir()
    for ep in (EP1, EP2, EP3, EP9):
        markdown_parser.write(bank / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00", "processed": False}, "Words.\n")
    _page(bank, "alpha-tool", {"name": "Alpha Tool", "type": "tool", "source_episodes": [EP1, EP2, EP3, EP9],
                               "aliases": ["AT"]})
    _page(bank, "beta-project", {"name": "Beta Project", "type": "project", "source_episodes": [EP1, EP2, EP9],
                                 "aliases": ["Alpha Tool"]})
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Test")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    # One Sleep batch read EP1..EP3 and created two skill pages the old way.
    for ep in (EP1, EP2, EP3):
        path = bank / "episodes" / f"{ep}.md"
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, {**parsed.frontmatter, "processed": True}, parsed.body)
    old = {"type": "skill", "status": "active", "confidence": 0.45, "created": "2026-10-08",
           "last_referenced": "2026-10-08", "source_episodes": [], "tags": [], "related": [], "version": 1}
    _page(bank, "checks-the-tracker", {**old, "name": "Checks the tracker"},
          "Before planning with Alpha Tool, reads Beta Project's tracker.\n")
    _page(bank, "prefers-short-answers", {**old, "name": "Prefers short answers"}, "Keeps answers short.\n")
    _alias(bank, "alpha-tool", "the tool")          # Sleep recorded a reference
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "Sleep cycle 2026-10-08\n\nentities/alpha-tool.md: update (source: ep_2026-03-02_1)")
    # The person merged a page into beta-project: its name became an alias, under the person's own commit.
    _alias(bank, "beta-project", "the lake house")
    _git(bank, "commit", "-q", "-am", "Inbox resolution: merge\n\nCicada-Author: user")
    return bank


def test_the_dry_run_counts_and_writes_nothing(bank):
    before = {p: p.read_text() for p in (bank / "entities").glob("*.md")}
    counts = repair.survey(bank).counts()
    assert counts["skill_pages"] == 2 and counts["skill_unsourced"] == 2
    assert counts["skill_groundable"] == 1 and counts["skill_no_evidence"] == 1
    assert counts["alias_pages"] == 1 and counts["alias_references"] == 1 and counts["alias_references_kept"] == 1
    assert counts["alias_names_other_page"] == 1     # beta-project lists another page's name: counted, kept
    assert counts["repaired"] == 0 and counts["committed"] is False
    assert {p: p.read_text() for p in (bank / "entities").glob("*.md")} == before
    assert "tracker" not in json.dumps(counts)


def test_apply_grounds_the_skill_on_its_batch_and_evidence_in_one_cicada_commit(bank):
    result = repair.apply(bank, sleep_running=lambda: False)
    assert result.repaired == 2 and result.committed
    fm = markdown_parser.parse(bank / "entities" / "checks-the-tracker.md").frontmatter
    # EP9 is outside the batch; EP3 had only one of the two named pages.
    assert fm["source_episodes"] == [EP1, EP2]
    assert fm["created"] == "2026-03-02" and fm["last_referenced"] == "2026-03-09"
    assert fm["decayed_through"] == "2026-10-08"         # the silence clock is where Cicada learned it
    assert fm["related"] == ["alpha-tool", "beta-project"]
    assert markdown_parser.parse(bank / "entities" / "checks-the-tracker.md").body.strip() == \
        "Before planning with Alpha Tool, reads Beta Project's tracker."
    untouched = markdown_parser.parse(bank / "entities" / "prefers-short-answers.md").frontmatter
    assert untouched["source_episodes"] == []
    assert markdown_parser.parse(bank / "entities" / "alpha-tool.md").frontmatter["aliases"] == ["AT"]
    # The person's merge is theirs: never removed by the repair (fix round 1, B2).
    assert markdown_parser.parse(bank / "entities" / "beta-project.md").frontmatter["aliases"] == \
        ["Alpha Tool", "the lake house"]
    log = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in log and "maintenance/skill-provenance" in log
    assert _git(bank, "status", "--porcelain") == ""
    assert repair.survey(bank).counts()["skill_groundable"] == 0      # idempotent


def test_a_page_with_uncommitted_changes_is_skipped(bank):
    path = bank / "entities" / "alpha-tool.md"
    path.write_text(path.read_text() + "\nhand edit\n")
    result = repair.apply(bank, sleep_running=lambda: False)
    assert result.dirty == 1
    assert markdown_parser.parse(path).frontmatter["aliases"] == ["AT", "the tool"]


def test_an_alias_the_person_added_again_after_sleep_is_theirs(bank):
    path = bank / "entities" / "alpha-tool.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "aliases": ["AT"]}, parsed.body)
    _git(bank, "commit", "-q", "-am", "Inbox resolution: drop alias")
    _alias(bank, "alpha-tool", "the tool")
    _git(bank, "commit", "-q", "-am", "Inbox resolution: add alias back")
    assert repair._sleep_added(bank, "entities/alpha-tool.md", ["the tool"]) == set()
    assert repair.survey(bank).counts()["alias_references_kept"] == 2


def test_list_shows_what_apply_would_remove(bank, capsys):
    assert repair_skills_aliases.main(["--bank", str(bank), "--list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["removals"] == {"alpha-tool": ["the tool"]} and out["repaired"] == 0


def test_refuses_while_sleep_runs(bank):
    before = {p: p.read_text() for p in (bank / "entities").glob("*.md")}
    with pytest.raises(repair.SleepRunning):
        repair.apply(bank, sleep_running=lambda: True)
    assert {p: p.read_text() for p in (bank / "entities").glob("*.md")} == before


def test_the_script_is_a_dry_run_unless_told(bank, capsys, monkeypatch):
    assert repair_skills_aliases.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["repaired"] == 0
    monkeypatch.setattr(repair_skills_aliases, "backend_running", lambda: True)
    assert repair_skills_aliases.main(["--bank", str(bank), "--apply"]) == 3
    assert repair_skills_aliases.main(["--bank", str(bank / "nope")]) == 2
