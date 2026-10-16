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
    # Sleep created a page with a reference among its aliases: provably Sleep's.
    _page(bank, "gamma-thing", {"name": "Gamma Thing", "type": "concept", "aliases": ["Gamma", "the thing"]})
    # Sleep updated alpha-tool and a reference landed on it — Sleep's merge or the person's uncommitted edit, which
    # Sleep's `git add -A` commits under the same subject: unproven, kept (fix round 2, B3).
    _alias(bank, "alpha-tool", "the tool")
    # A page the person edited by hand and Sleep merely swept up (a porcelain line, no `source:`).
    _alias(bank, "beta-project", "the boathouse")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "Sleep cycle 2026-10-08\n\n"
         "entities/alpha-tool.md: update (source: ep_2026-03-02_1, trigger: sleep/extraction)\n"
         "entities/gamma-thing.md: create (source: ep_2026-03-02_1, trigger: sleep/promotion)\n"
         "entities/beta-project.md: modified (trigger: manual)")
    # The person merged a page into beta-project: its name became an alias, under the person's own commit.
    _alias(bank, "beta-project", "the lake house")
    _git(bank, "commit", "-q", "-am", "Inbox resolution: merge\n\nCicada-Author: user")
    return bank


def test_the_dry_run_counts_and_writes_nothing(bank):
    before = {p: p.read_text() for p in (bank / "entities").glob("*.md")}
    counts = repair.survey(bank).counts()
    assert counts["skill_pages"] == 2 and counts["skill_unsourced"] == 2
    assert counts["skill_groundable"] == 1 and counts["skill_no_evidence"] == 1
    assert counts["alias_pages"] == 1 and counts["alias_references"] == 1
    assert counts["alias_references_kept"] == 3 and counts["alias_references_unproven"] == 2
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
    assert markdown_parser.parse(bank / "entities" / "gamma-thing.md").frontmatter["aliases"] == ["Gamma"]
    # Unproven (a Sleep update, or a hand edit Sleep swept up) and the person's merge: never removed (B2, B3).
    assert markdown_parser.parse(bank / "entities" / "alpha-tool.md").frontmatter["aliases"] == ["AT", "the tool"]
    assert markdown_parser.parse(bank / "entities" / "beta-project.md").frontmatter["aliases"] == \
        ["Alpha Tool", "the boathouse", "the lake house"]
    log = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in log and "maintenance/skill-provenance" in log
    assert _git(bank, "status", "--porcelain") == ""
    assert repair.survey(bank).counts()["skill_groundable"] == 0      # idempotent


def test_a_page_with_uncommitted_changes_is_skipped(bank):
    path = bank / "entities" / "gamma-thing.md"
    path.write_text(path.read_text() + "\nhand edit\n")
    result = repair.apply(bank, sleep_running=lambda: False)
    assert result.dirty == 1
    assert markdown_parser.parse(path).frontmatter["aliases"] == ["Gamma", "the thing"]


def test_an_alias_the_person_added_again_after_sleep_is_theirs(bank):
    path = bank / "entities" / "gamma-thing.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "aliases": ["Gamma"]}, parsed.body)
    _git(bank, "commit", "-q", "-am", "Inbox resolution: drop alias")
    _alias(bank, "gamma-thing", "the thing")
    _git(bank, "commit", "-q", "-am", "Inbox resolution: add alias back")
    assert repair._sleep_added(bank, "entities/gamma-thing.md", ["the thing"]) == (set(), set())
    assert repair.survey(bank).counts()["alias_references"] == 0


def test_a_hand_edit_a_later_sleep_commit_swept_up_is_kept(bank):
    """B3: Sleep created the alias, the person removed it, then typed it back by hand and left it uncommitted; the
    next Sleep cycle's `git add -A` commits it under Sleep's subject. Its latest addition is not Sleep's own create."""
    path = bank / "entities" / "gamma-thing.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "aliases": ["Gamma"]}, parsed.body)
    _git(bank, "commit", "-q", "-am", "Inbox resolution: drop alias")
    _alias(bank, "gamma-thing", "the thing")
    _git(bank, "commit", "-q", "-am", "Sleep cycle 2026-10-09\n\nentities/gamma-thing.md: modified (trigger: manual)")
    assert repair._sleep_added(bank, "entities/gamma-thing.md", ["the thing"]) == (set(), {"the thing"})
    assert repair.survey(bank).counts()["alias_references"] == 0


def test_list_shows_what_apply_would_remove(bank, capsys):
    assert repair_skills_aliases.main(["--bank", str(bank), "--list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["removals"] == {"gamma-thing": ["the thing"]} and out["repaired"] == 0
    assert out["unproven"] == {"alpha-tool": ["the tool"], "beta-project": ["the boathouse"]}


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


# --- owner ruling 2026-10-09: skill pages with no traceable conversation are archived, on request, when git proves them ---


def _decay(bank, stem, *, confidence, status, through, edit_body=None, folded=False):
    """Sleep's decay of a page: its own `cicada` commit (or folded into a cycle commit), with Sleep's decay line."""
    path = bank / "entities" / f"{stem}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "confidence": confidence, "status": status,
                                 "decayed_through": through}, edit_body or parsed.body)
    subject = f"Sleep cycle {through}" + ("" if folded else " (decay)")
    _git(bank, "commit", "-q", "-am", f"{subject}\n\n"
         f"entities/{stem}.md: decay_nudge (source: n/a, trigger: sleep/decay)\n\nCicada-Author: cicada")


def test_the_dry_run_counts_what_the_archive_would_take_and_writes_nothing(bank, capsys):
    before = {p: p.read_text() for p in (bank / "entities").glob("*.md")}
    for archive in (False, True):
        counts = repair.survey(bank, archive=archive).counts()
        assert counts["skill_archivable"] == 1 and counts["skill_archive_unproven"] == 0
        assert counts["archived"] == 0 and counts["committed"] is False
    assert {p: p.read_text() for p in (bank / "entities").glob("*.md")} == before
    assert repair_skills_aliases.main(["--bank", str(bank), "--list", "--archive-unsourced"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["archive"] == ["prefers-short-answers"] and out["archive_unproven"] == []
    assert {p: p.read_text() for p in (bank / "entities").glob("*.md")} == before


def test_without_the_flag_nothing_is_archived(bank):
    result = repair.apply(bank, sleep_running=lambda: False)
    assert result.archived == 0
    assert markdown_parser.parse(bank / "entities" / "prefers-short-answers.md").frontmatter["status"] == "active"


def test_the_archive_sets_status_in_the_same_cicada_commit_and_writes_no_inbox_item(bank):
    commits = int(_git(bank, "rev-list", "--count", "HEAD"))
    result = repair.apply(bank, sleep_running=lambda: False, archive=True)
    assert result.archived == 1 and result.repaired == 2 and result.committed
    page = markdown_parser.parse(bank / "entities" / "prefers-short-answers.md")
    assert page.frontmatter["status"] == "archived" and page.frontmatter["source_episodes"] == []
    assert page.body.strip() == "Keeps answers short."
    # The grounded skill is grounded, not archived.
    assert markdown_parser.parse(bank / "entities" / "checks-the-tracker.md").frontmatter["status"] == "active"
    assert int(_git(bank, "rev-list", "--count", "HEAD")) == commits + 1
    log = _git(bank, "log", "-1", "--format=%B")
    assert "entities/prefers-short-answers.md: archived (trigger: maintenance/skill-archive)" in log
    assert "entities/checks-the-tracker.md: repaired (trigger: maintenance/skill-provenance)" in log
    assert "Cicada-Author: cicada" in log and "; unsourced skill pages archived: 1 page(s)" in log
    assert _git(bank, "status", "--porcelain") == ""
    assert not (bank / "inbox").exists() or not list((bank / "inbox").iterdir())
    again = repair.survey(bank, archive=True).counts()
    assert again["skill_archivable"] == 0 and again["skill_archive_unproven"] == 0     # idempotent


def test_a_page_only_sleeps_decay_touched_is_still_proven(bank):
    _decay(bank, "prefers-short-answers", confidence=0.38, status="decaying", through="2026-10-15")
    _decay(bank, "prefers-short-answers", confidence=0.36, status="decaying", through="2026-10-22", folded=True)
    assert repair.apply(bank, sleep_running=lambda: False, archive=True).archived == 1
    fm = markdown_parser.parse(bank / "entities" / "prefers-short-answers.md").frontmatter
    assert fm["status"] == "archived" and fm["confidence"] == 0.36


def _unproven(bank):
    counts = repair.survey(bank, archive=True).counts()
    assert counts["skill_archivable"] == 0 and counts["skill_archive_unproven"] == 1
    assert repair.apply(bank, sleep_running=lambda: False, archive=True).archived == 0
    assert markdown_parser.parse(bank / "entities" / "prefers-short-answers.md").frontmatter["status"] != "archived"


def test_a_page_the_person_answered_about_is_kept(bank):
    path = bank / "entities" / "prefers-short-answers.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "confidence": 0.6}, parsed.body)
    _git(bank, "commit", "-q", "-am", "Inbox resolution: keep\n\nCicada-Author: user")
    _unproven(bank)


def test_a_hand_edit_a_sleep_commit_swept_up_is_kept(bank):
    path = bank / "entities" / "prefers-short-answers.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, "Keeps answers short, unless asked.\n")
    _git(bank, "commit", "-q", "-am", "Sleep cycle 2026-10-12\n\n"
         "entities/prefers-short-answers.md: updated (trigger: sleep/extraction)")
    _unproven(bank)


def test_a_hand_edit_a_decay_commit_carried_is_kept(bank):
    # A decay commit stages the whole file: the decay line is Sleep's, the new body is not.
    _decay(bank, "prefers-short-answers", confidence=0.38, status="decaying", through="2026-10-15",
           edit_body="Keeps answers short. Mine.\n")
    _unproven(bank)


def test_a_key_decay_never_writes_is_kept(bank):
    path = bank / "entities" / "prefers-short-answers.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "confidence": 0.38, "status": "decaying",
                                 "decayed_through": "2026-10-15", "tags": ["mine"]}, parsed.body)
    _git(bank, "commit", "-q", "-am", "Sleep cycle 2026-10-15 (decay)\n\n"
         "entities/prefers-short-answers.md: decay_nudge (source: n/a, trigger: sleep/decay)")
    _unproven(bank)


def test_a_skill_page_another_writer_created_is_kept(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Test")
    _git(bank, "config", "user.email", "test@example.com")
    _page(bank, "my-habit", {"name": "My habit", "type": "skill", "status": "active", "confidence": 0.5,
                             "created": "2026-10-08", "last_referenced": "2026-10-08", "source_episodes": [],
                             "tags": [], "related": [], "version": 1}, "Mine.\n")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "Inbox resolution: confirm\n\nCicada-Author: user")
    counts = repair.survey(bank, archive=True).counts()
    assert counts["skill_archivable"] == 0 and counts["skill_archive_unproven"] == 1


def test_a_page_the_old_writer_did_not_shape_is_kept(bank):
    """Sleep's commit added it, but not with the old Stage-4 writer's frontmatter: a hand-made page Sleep swept up."""
    _page(bank, "hand-made", {"name": "Hand made", "type": "skill", "status": "active", "source_episodes": [],
                              "notes": "mine"}, "Mine.\n")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m",
         "Sleep cycle 2026-10-09\n\nentities/hand-made.md: created (trigger: sleep/extraction)")
    counts = repair.survey(bank, archive=True).counts()
    assert counts["skill_archivable"] == 1 and counts["skill_archive_unproven"] == 1


def test_an_archive_candidate_with_uncommitted_changes_is_skipped(bank):
    path = bank / "entities" / "prefers-short-answers.md"
    path.write_text(path.read_text() + "\nhand edit\n")
    result = repair.apply(bank, sleep_running=lambda: False, archive=True)
    assert result.archived == 0
    assert markdown_parser.parse(path).frontmatter["status"] == "active"


def test_the_archive_refuses_while_sleep_runs(bank, monkeypatch):
    before = {p: p.read_text() for p in (bank / "entities").glob("*.md")}
    with pytest.raises(repair.SleepRunning):
        repair.apply(bank, sleep_running=lambda: True, archive=True)
    monkeypatch.setattr(repair_skills_aliases, "backend_running", lambda: True)
    assert repair_skills_aliases.main(["--bank", str(bank), "--apply", "--archive-unsourced"]) == 3
    assert {p: p.read_text() for p in (bank / "entities").glob("*.md")} == before
