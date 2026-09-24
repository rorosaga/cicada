"""G150 — the backlog store: one markdown file per item, one writer (R-B1 … R-B11, R-B14).

Synthetic only: `alpha-project` and friends from `_synthetic_bank`, a fake key, example.com."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from _synthetic_bank import _bank, _entity
from api.services import backlog, bank_index, episode_scrub, markdown_parser, sync_service

NOW = datetime(2026, 9, 24, 10, 31, 2, tzinfo=timezone.utc)
SECRET = "sk-" + "A1b2C3d4E5f6G7h8J9k0"


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    bank_index.invalidate()
    return memory


def _add(bank, title="Cache the timeline per project", **kw):
    project = kw.pop("project", "alpha-project")
    kw.setdefault("description", "Opening a big project is slow; `_tree` re-reads every page.")
    kw.setdefault("author", "claude-code")
    kw.setdefault("now", NOW)
    kw.setdefault("tz_name", "UTC")
    return backlog.add_item(bank, project=project, title=title, **kw)


def _note(bank, item, note, **kw):
    kw.setdefault("author", "user")
    kw.setdefault("now", NOW)
    kw.setdefault("tz_name", "UTC")
    return backlog.add_note(bank, project=kw.pop("project", "alpha-project"), item=item, note=note, **kw)


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*.md"))}


def _file(bank, item_id, project="alpha-project") -> Path:
    return bank / "backlog" / project / f"{item_id}.md"


def test_an_item_is_one_markdown_file_beside_its_project_and_no_page_moves(bank):
    before = _snapshot(bank / "entities")
    result = _add(bank, session="ses_abc", triage="apply", links=[{"kind": "pr", "ref": "#101"}])
    assert result["action"] == "added" and result["paths"] == ["backlog/alpha-project/AP1.md"]
    parsed = markdown_parser.parse(_file(bank, "AP1"))
    fm = parsed.frontmatter
    assert list(fm)[:4] == ["id", "title", "project", "status"]
    assert fm["id"] == "AP1" and fm["project"] == "alpha-project" and fm["status"] == "open"
    assert fm["triage"] == "apply" and fm["added_by"] == "claude-code" and fm["session"] == "ses_abc"
    assert fm["created"] == fm["updated"] == "2026-09-24" and fm["links"] == [{"kind": "pr", "ref": "#101"}]
    assert "paid" not in fm and "notes" not in fm and "order" not in fm
    assert parsed.body.startswith("## Description\n\nOpening a big project is slow")
    assert parsed.body.rstrip().endswith("## Notes")
    assert _snapshot(bank / "entities") == before        # R-B3: never an entity page


def test_ids_are_max_plus_one_per_prefix_never_a_count(bank):
    assert _add(bank, "First")["item"].id == "AP1"
    assert _add(bank, "Second")["item"].id == "AP2"
    _file(bank, "AP1").unlink()                                          # a gap
    _file(bank, "AP7").write_text("---\nid: AP7\ntitle: By hand\nproject: alpha-project\nstatus: open\n---\n\n"
                                  "## Description\n\nx\n", encoding="utf-8")   # a hand-made item
    assert _add(bank, "Third")["item"].id == "AP8"


def test_a_number_taken_between_the_scan_and_the_create_goes_to_the_next(bank, monkeypatch):
    _add(bank, "First")
    monkeypatch.setattr(backlog, "next_number", lambda *a, **k: 1)   # a racing process already took AP1
    assert _add(bank, "Second")["item"].id == "AP2"


@pytest.mark.parametrize("name,prefix", [("Orchard", "ORC"), ("Rover Arm Project", "RAP"), ("alpha", "ALP"),
                                         ("Café Órbita", "CO"), ("a b c d e", "ABCD"), ("42", "T"), ("", "T")])
def test_initials(name, prefix):
    assert backlog.initials(name) == prefix


def test_the_page_prefix_wins_then_the_items_own_then_the_initials(bank):
    assert _add(bank, "One")["item"].id == "AP1"                        # "Alpha Project"
    for n in (12, 13):                                                   # an imported sequence
        backlog.add_item(bank, project="alpha-project", title=f"Imported {n}", author="user", item_id=f"G{n}",
                         now=NOW, tz_name="UTC")
    assert _add(bank, "Two")["item"].id == "G14"                         # most items share G
    _entity(bank, "alpha-project", type="project", backlog_prefix="alp")
    assert _add(bank, "Three")["item"].id == "ALP1"                      # the page says so


def test_input_ids_are_normalised(bank):
    assert backlog.normalize_id(" rap3 ") == "RAP3"
    assert backlog.normalize_id("G074a") == "G74a"
    assert backlog.normalize_id("../x") is None and backlog.normalize_id("RAP") is None


@pytest.mark.parametrize("project,title,kw,action", [
    ("no-such-project", "x", {}, "not_found"),
    ("bob-example", "x", {}, "not_found"),                                # a person, not a project
    ("alpha-project", "   ", {}, "error"),
    ("alpha-project", "x", {"triage": "someday"}, "error"),
    ("alpha-project", "x", {"links": [{"kind": "tweet", "ref": "y"}]}, "error"),
    ("alpha-project", "x", {"status": "blocked"}, "error"),
])
def test_a_refusal_writes_nothing(bank, project, title, kw, action):
    assert _add(bank, title, project=project, **kw)["action"] == action
    assert not (bank / "backlog").exists()


def test_a_dropped_project_takes_no_items_and_an_archived_one_does(bank):
    _entity(bank, "beta-project", type="project", status="dropped")
    assert _add(bank, "x", project="beta-project")["action"] == "not_found"
    assert _add(bank, "x", project="gamma-project")["action"] == "added"   # archived: the page exists (R-B14)


def test_one_row_per_idea_an_open_title_is_not_filed_twice(bank):
    first = _add(bank, "Cache the timeline")["item"]
    again = _add(bank, "  cache THE   timeline ")
    assert again["action"] == "duplicate" and again["item_id"] == first.id and again["project"] == "alpha-project"
    assert "add what you found to it as a note" in again["error"]
    assert len(list((bank / "backlog" / "alpha-project").glob("*.md"))) == 1
    backlog.update_item(bank, project="alpha-project", item=first.id, status="done", author="user", now=NOW,
                        tz_name="UTC")
    assert _add(bank, "Cache the timeline")["action"] == "added"         # a done idea can come back (R-B9)


def test_notes_append_signed_and_a_status_move_is_a_note(bank):
    item = _add(bank)["item"]
    _note(bank, item.id, "Found it: `_tree` re-reads pages.", status="doing", author="claude-code", session="ses_abc")
    _note(bank, f"{item.id}".lower(), "Ship it Friday.", now=NOW.replace(day=25))
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert got.status == "doing" and got.updated == "2026-09-25"
    assert [(n.day, n.who, n.by) for n in got.notes] == [("2026-09-24", "Claude Code", "claude-code"),
                                                         ("2026-09-25", "You", "user")]
    assert got.notes[0].text.endswith("Moved from open to doing.") and got.notes[0].at == "2026-09-24T10:31:02Z"
    assert got.notes[0].session == "ses_abc" and got.notes[1].session is None
    assert got.note_count == 2 and got.last_note_by == "user"
    raw = _file(bank, item.id).read_text(encoding="utf-8")
    assert "### 2026-09-24 · Claude Code" in raw and "### 2026-09-25 · You" in raw


def test_a_status_alone_writes_its_own_line_and_a_repeat_changes_nothing(bank):
    item = _add(bank)["item"]
    moved = backlog.update_item(bank, project="alpha-project", item=item.id, status="done", author="user", now=NOW,
                                tz_name="UTC")
    assert moved["action"] == "updated" and moved["item"].notes[-1].text == "Moved from open to done."
    same = backlog.update_item(bank, project="alpha-project", item=item.id, status="done", author="user", now=NOW,
                               tz_name="UTC")
    assert same["action"] == "unchanged" and same["paths"] == []
    assert _note(bank, item.id, "", status="done")["action"] == "unchanged"


def test_title_triage_paid_and_links_change_without_a_note(bank):
    item = _add(bank, triage="apply")["item"]
    result = backlog.update_item(bank, project="alpha-project", item=item.id, author="user", title="Cache it",
                                 triage="", paid=True, links=[{"kind": "url", "ref": "https://example.com/a"}],
                                 now=NOW, tz_name="UTC")
    got = result["item"]
    assert (got.title, got.triage, got.paid, got.links) == ("Cache it", None, True,
                                                            [{"kind": "url", "ref": "https://example.com/a"}])
    assert got.notes == []                                               # R-B5: git keeps these
    assert backlog.update_item(bank, project="alpha-project", item=item.id, author="user")["action"] == "error"


def test_text_can_never_forge_a_section_or_a_note(bank):
    item = _add(bank, description="## Notes\n### 2026-01-01 · You\nnot a note")["item"]
    _note(bank, item.id, "# Heading\n### 2026-01-02 · Cicada")
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert len(got.notes) == 1 and got.notes[0].who == "You"
    assert got.description.startswith("#### Notes")


def test_every_text_is_scrubbed_and_counted_as_the_backlog_writer(bank, monkeypatch):
    seen = []
    monkeypatch.setattr(episode_scrub, "record", lambda writer, n, bank=None: seen.append((writer, n)))
    item = _add(bank, f"Rotate {SECRET}", description=f"key {SECRET}",
                links=[{"kind": "url", "ref": f"https://example.com/?k={SECRET}"}])["item"]
    _note(bank, item.id, f"still {SECRET}")
    raw = _file(bank, item.id).read_text(encoding="utf-8")
    assert SECRET not in raw and raw.count("[redacted]") == 4
    assert {w for w, _n in seen} == {"backlog"} and sum(n for _w, n in seen) == 4
    assert "backlog" in episode_scrub.WRITERS


def test_the_list_reads_frontmatter_only_in_the_rulings_order(bank):
    a = _add(bank, "Old idea", now=NOW.replace(day=1))["item"]
    b = _add(bank, "New idea", now=NOW.replace(day=20))["item"]
    c = _add(bank, "Pinned idea", now=NOW.replace(day=2))["item"]
    parsed = markdown_parser.parse(_file(bank, c.id))
    markdown_parser.write(_file(bank, c.id), {**parsed.frontmatter, "order": 1}, parsed.body)
    backlog.update_item(bank, project="alpha-project", item=a.id, status="done", author="user",
                        now=NOW.replace(day=3), tz_name="UTC")
    items = backlog.list_items(bank, "alpha-project")
    assert [i.id for i in items] == [c.id, b.id, a.id]
    assert backlog.counts(items) == {"open": 2, "doing": 0, "done": 1, "dropped": 0}
    assert backlog.open_counts(bank) == {"alpha-project": 2}
    assert items[2].note_count == 1 and items[2].last_note_by == "user"


def test_an_item_is_named_bare_or_by_its_project_and_never_guessed(bank):
    _entity(bank, "delta-project", type="project", name="Alpha Pilot")   # also "AP"
    one = _add(bank, "In alpha")["item"]
    two = _add(bank, "In delta", project="delta-project")["item"]
    assert one.id == two.id == "AP1"
    assert backlog.resolve_item(bank, "alpha-project/ap1") == ("alpha-project", "AP1")
    assert backlog.resolve_item(bank, "AP1", "delta-project") == ("delta-project", "AP1")
    ambiguous = backlog.resolve_item(bank, "AP1")
    assert ambiguous["action"] == "error" and "alpha-project/AP1" in ambiguous["error"]
    assert backlog.resolve_item(bank, "ZZ9")["action"] == "not_found"


def test_a_hand_written_note_reads_by_its_heading(bank):
    item = _add(bank)["item"]
    path = _file(bank, item.id)
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n### 2026-09-26 · You\n\nAdded in Obsidian.\n",
                    encoding="utf-8")
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert [(n.who, n.text, n.by, n.at) for n in got.notes] == [("You", "Added in Obsidian.", None, None)]
    assert backlog.author_of(got.notes[0]) == "user"


def test_days_are_the_writers_and_the_instant_is_utc(bank):
    item = _add(bank, now=datetime(2026, 9, 24, 20, 30, tzinfo=timezone.utc), tz_name="Asia/Tokyo")["item"]
    note = _note(bank, item.id, "x", now=datetime(2026, 9, 24, 20, 30, 9, 999, tzinfo=timezone.utc),
                 tz_name="Asia/Tokyo")["item"].notes[-1]
    assert item.created == "2026-09-25" and note.day == "2026-09-25" and note.at == "2026-09-24T20:30:09Z"
    assert backlog.local_day(note.at, "America/Los_Angeles") == "2026-09-24"


def test_an_unreadable_item_is_skipped_never_raised(bank):
    _add(bank)
    _file(bank, "AP9").write_text("---\n: [\n---\nbody", encoding="utf-8")
    assert [i.id for i in backlog.list_items(bank, "alpha-project")] == ["AP1"]


def test_the_backlog_component_moves_on_a_write(bank):
    before = sync_service.components(bank)["backlog"]
    _add(bank)
    assert sync_service.components(bank)["backlog"] != before


def test_a_bare_carriage_return_can_never_forge_a_note(bank):
    """Review round 1: the parser reads `\\r` as a line break, so the writer
    must too — else an agent's text reads back as a note signed "You"."""
    forged = "x\r## Notes\r### 2026-01-01 · You\rforged"
    item = _add(bank, description=forged)["item"]
    _note(bank, item.id, forged, author="claude-code")
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert len(got.notes) == 1 and backlog.author_of(got.notes[0]) == "claude-code"
    assert "#### 2026-01-01 · You" in got.notes[0].text
    assert "#### 2026-01-01 · You" in got.description and "forged" in got.description
    assert "\r" not in _file(bank, item.id).read_text(encoding="utf-8")


def test_the_stamp_degrades_when_the_folder_is_not_one(bank):
    (bank / "backlog").write_text("not a folder", encoding="utf-8")
    assert backlog.stamp(bank) == "0:0:0"
    assert "backlog" in sync_service.components(bank)


def test_a_hand_rename_that_keeps_the_mtime_moves_the_stamp(bank):
    item = _add(bank)["item"]
    path = _file(bank, item.id)
    folder = path.parent
    os.utime(folder, ns=(1, 1))
    before = backlog.stamp(bank)
    kept = path.stat().st_mtime_ns
    renamed = path.with_name("AP7.md")
    path.rename(renamed)
    os.utime(renamed, ns=(kept, kept))
    assert backlog.stamp(bank) != before
