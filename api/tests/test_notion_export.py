"""G219 slice 1: a Notion export (Markdown & CSV zip) through the one intake. Pages and database rows become
documents in the person's own words, one episode per row, keyed by Notion's own page id, dated by a row's Created
property; a second import of the same zip changes nothing, an edited page updates in place. A synthetic export with
placeholders only (`alpha-project`, `bob-example`)."""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, channel_items, episode_staging, markdown_parser, notion_export, source_overview

ROOT_ID = "0" * 31 + "1"
IDEAS_ID = "a" * 32
ROW1_ID = "b" * 31 + "1"
ROW2_ID = "b" * 31 + "2"
SUB_ID = "c" * 32
EMPTY_ID = "d" * 32

PAGE = f"""# Working notes

Plans for alpha-project this autumn. Ask bob-example about the [design doc](Working%20notes%20{ROOT_ID}/Design%20{SUB_ID}.md).

![diagram](Working%20notes%20{ROOT_ID}/diagram.png)

Reference: [the spec](https://example.com/spec)
"""
SUB = """# Design

Note: the second line is the person's words, never a property.
"""
ROW1 = """# Offline mode for alpha-project

Status: Idea
Tags: mobile
Created: September 3, 2024 2:10 PM

Sync later, read everything now.
"""
ROW2 = """# A very long idea title that Notion cut in its file

Status: Doing
Created: March 1, 2025 9:00 AM
"""
CSV = ("﻿Name,Status,Tags,Created\n"
       "Offline mode for alpha-project,Idea,mobile,\"September 3, 2024 2:10 PM\"\n"
       "A very long idea title that Notion cut in its file name for sure,Doing,,\"March 1, 2025 9:00 AM\"\n"
       "Row with no page of its own,Parked,,\"January 5, 2026\"\n")


def _export(page=PAGE, row1=ROW1, nested=False) -> bytes:
    files = {
        f"Working notes {ROOT_ID}.md": page,
        f"Working notes {ROOT_ID}/Design {SUB_ID}.md": SUB,
        f"Working notes {ROOT_ID}/diagram.png": "png-bytes",
        f"Working notes {ROOT_ID}/Empty parent {EMPTY_ID}.md": "# Empty parent\n",
        f"Project ideas {IDEAS_ID}.csv": CSV,
        f"Project ideas {IDEAS_ID}_all.csv": CSV,
        f"Project ideas {IDEAS_ID}/Offline mode for alpha-project {ROW1_ID}.md": row1,
        f"Project ideas {IDEAS_ID}/A very long idea title that Notion cut {ROW2_ID}.md": ROW2,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    if not nested:
        return buf.getvalue()
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("Export-0000-Part-1.zip", buf.getvalue())
    return outer.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _episodes(memory):
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith("notion:"):
            out[sid] = (path, parsed)
    return out


def _import(c, data, name="Export-0000.zip"):
    return c.post("/intake/import", files={"file": (name, data, "application/zip")})


def test_the_sniff_names_a_notion_export_with_its_pages_rows_and_titles(client):
    c, _ = client
    r = c.post("/intake/sniff", files={"file": ("Export-0000.zip", _export(), "application/zip")})
    body = r.json()
    assert r.status_code == 200, r.text
    assert (body["recognized"], body["kind"], body["vendor"], body["origin"]) == (
        True, "chat", "notion", "notion-export")
    assert body["counts"]["pages"] == 2 and body["counts"]["rows"] == 3
    assert body["delta"] == {"new": 5, "grown": 0, "unchanged": 0}
    assert {t["title"] for t in body["titles"]} >= {"Working notes", "Design", "Offline mode for alpha-project"}
    assert any("left out" in w for w in body["warnings"])


def test_an_import_stages_one_episode_per_page_and_per_row_and_a_second_changes_nothing(client):
    c, memory = client
    r = _import(c, _export())
    assert r.status_code == 200, r.text
    assert (r.json()["episodesStaged"], r.json()["origin"]) == (5, "notion-export")
    eps = _episodes(memory)
    assert set(eps) == {f"notion:{ROOT_ID}", f"notion:{SUB_ID}", f"notion:{ROW1_ID}", f"notion:{ROW2_ID}",
                        f"notion:{IDEAS_ID}:" + __import__("hashlib").sha256(
                            b"Row with no page of its own").hexdigest()[:12]}
    for _, ep in eps.values():
        fm = ep.frontmatter
        assert (fm["origin"], fm["evidence_kind"], fm["processed"]) == ("notion-export", "user", False)
    again = _import(c, _export())
    assert again.json()["episodesStaged"] == 0 and again.json()["duplicatesSkipped"] == 5
    assert len(_episodes(memory)) == 5


def test_a_row_is_dated_by_its_created_property_and_carries_the_csv_properties(client):
    c, memory = client
    _import(c, _export())
    path, ep = _episodes(memory)[f"notion:{ROW1_ID}"]
    assert path.name.startswith("ep_2024-09-03_")
    assert ep.frontmatter["notion_kind"] == "row" and ep.frontmatter["notion_database"] == IDEAS_ID
    assert ep.body.startswith("# Offline mode for alpha-project\n\n**Database:** Project ideas")
    assert "**Status:** Idea" in ep.body and "**Tags:** mobile" in ep.body
    assert "Sync later, read everything now." in ep.body
    # A title Notion cut in the file name still finds its page; the CSV's full title wins.
    _, long_row = _episodes(memory)[f"notion:{ROW2_ID}"]
    assert long_row.frontmatter["title"].endswith("for sure")
    assert "**Status:** Doing" in long_row.body


def test_a_page_keeps_its_words_and_breadcrumb_and_loses_relative_paths(client):
    c, memory = client
    _import(c, _export())
    _, page = _episodes(memory)[f"notion:{ROOT_ID}"]
    assert "Ask bob-example about the design doc." in page.body
    assert ".md" not in page.body and "diagram.png" not in page.body
    assert "[the spec](https://example.com/spec)" in page.body
    _, sub = _episodes(memory)[f"notion:{SUB_ID}"]
    assert "**In:** Working notes" in sub.body
    assert "Note: the second line is the person's words" in sub.body
    assert f"notion:{EMPTY_ID}" not in _episodes(memory)


def test_an_edited_page_updates_in_place(client):
    c, memory = client
    _import(c, _export())
    path, _ = _episodes(memory)[f"notion:{ROW1_ID}"]
    r = _import(c, _export(row1=ROW1.replace("Sync later", "Sync on wifi only")))
    assert r.json()["episodesUpdated"] == 1 and r.json()["episodesStaged"] == 0
    same, ep = _episodes(memory)[f"notion:{ROW1_ID}"]
    assert same == path and "Sync on wifi only" in ep.body and ep.frontmatter["processed"] is False


def test_a_big_export_of_part_zips_is_read_one_level_down(client):
    c, memory = client
    assert _import(c, _export(nested=True)).json()["episodesStaged"] == 5


def test_pasted_secrets_are_scrubbed(client):
    c, memory = client
    _import(c, _export(page=PAGE + "\nkey sk-ant-api03-" + "z" * 40 + "\n"))
    path, _ = _episodes(memory)[f"notion:{ROOT_ID}"]
    assert "sk-ant" not in path.read_text()


def test_a_chat_export_zip_is_never_read_as_notion():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("conversations.json", "[]")
        zf.writestr(f"Some page {ROOT_ID}.md", "# x\n\ny\n")
    assert not notion_export.looks_like(zipfile.ZipFile(io.BytesIO(buf.getvalue())))


def test_notion_dates_parse_in_the_shapes_notion_writes():
    assert notion_export.parse_date("October 1, 2026 3:04 PM").date().isoformat() == "2026-10-01"
    assert notion_export.parse_date("2026/10/01").date().isoformat() == "2026-10-01"
    assert notion_export.parse_date("October 1, 2026 → October 3, 2026").date().isoformat() == "2026-10-01"
    assert notion_export.parse_date("2026-10-01T12:00:00+00:00").tzinfo is not None
    assert notion_export.parse_date("someday") is None


def test_a_document_draft_keeps_its_body_writer_and_extras():
    draft = episode_staging.draft_from_export({"title": "T", "source_id": "notion:x", "body": "words",
                                               "writer": "notion", "extra": {"evidence_kind": "user"}})
    assert (draft.body, draft.writer, draft.extra, draft.turns) == ("words", "notion", {"evidence_kind": "user"}, [])


def test_the_notion_row_and_overview_entry(client):
    c, memory = client
    rows = {r["id"]: r for r in c.get("/sources/channels").json()["channels"]}
    assert rows["notion"]["connected"] is False
    _import(c, _export())
    bank_index.invalidate()
    rows = {r["id"]: r for r in c.get("/sources/channels").json()["channels"]}
    assert rows["notion"]["connected"] is True and rows["notion"]["count"] == 5
    assert channel_items.known(memory, "notion")
    spec = next(s for s in source_overview.CATALOG if s.id == "notion")
    assert (spec.kind, spec.origins) == ("import", ("notion-export",))


# --- Review of #455 -------------------------------------------------------------------------------------------------

def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_b1_only_pages_and_csvs_are_ever_read_and_a_bomb_stays_unread(monkeypatch):
    """A zero-filled image compresses to almost nothing and inflates to anything: it is never opened. A page past the
    per-file cap is left out and said, never read past its cap."""
    monkeypatch.setattr(notion_export, "MAX_MEMBER_BYTES", 64 * 1024)
    data = _zip({f"Working notes {ROOT_ID}.md": PAGE, "photo.png": b"\0" * (8 * 1024 * 1024),
                 f"Huge page {SUB_ID}.md": "# Huge\n\n" + "x" * (200 * 1024)})
    opened: list[str] = []
    real_open = zipfile.ZipFile.open

    def spy(self, name, *a, **kw):
        opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return real_open(self, name, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)
    parsed = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(data)))
    assert "photo.png" not in opened
    assert [e["source_id"] for e in parsed.episodes] == [f"notion:{ROOT_ID}"]
    assert any("1 other file" in w and "never read" in w for w in parsed.warnings)
    assert any(w.startswith("Left out: Huge page") and "larger than" in w for w in parsed.warnings)


def test_b1_the_total_read_is_capped(monkeypatch):
    monkeypatch.setattr(notion_export, "MAX_TOTAL_BYTES", 300)
    pages = {f"Page {i} {i:032x}.md": "# P\n\n" + "w" * 200 for i in range(1, 4)}
    parsed = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(_zip(pages))))
    assert len(parsed.episodes) == 1
    assert sum(1 for w in parsed.warnings if w.startswith("Left out:")) == 2


def test_b1_a_zip_inside_a_part_is_never_opened_and_is_said(client):
    deep = _zip({f"Deep page {SUB_ID}.md": "# Deep\n\nthree levels down\n"})
    part = _zip({f"Working notes {ROOT_ID}.md": PAGE, "inner.zip": deep})
    outer = _zip({"Export-0000-Part-1.zip": part})
    parsed = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(outer)))
    assert [e["source_id"] for e in parsed.episodes] == [f"notion:{ROOT_ID}"]
    assert any("inner.zip: a zip inside a part, not opened" in w for w in parsed.warnings)
    c, _ = client
    sniff = c.post("/intake/sniff", files={"file": ("Export-0000.zip", outer, "application/zip")}).json()
    assert any("not opened" in w for w in sniff["warnings"]), "the preview says what was left out"


def test_b1_a_part_over_its_cap_is_said(monkeypatch):
    monkeypatch.setattr(notion_export, "MAX_PART_BYTES", 100)
    outer = _zip({"Export-0000-Part-1.zip": _zip({f"Working notes {ROOT_ID}.md": PAGE * 5}),
                  f"Top {SUB_ID}.md": "# Top\n\nwords\n"})
    parsed = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(outer)))
    assert any("Export-0000-Part-1.zip: a part larger than" in w for w in parsed.warnings)


def test_b2_an_undated_page_is_untimed_and_a_dated_row_is_not(client):
    from api.services import episode_time

    c, memory = client
    _import(c, _export())
    eps = _episodes(memory)
    page = eps[f"notion:{ROOT_ID}"][1].frontmatter
    row = eps[f"notion:{ROW1_ID}"][1].frontmatter
    assert page["source"] == "notion-export-undated" and page["origin"] == "notion-export"
    assert episode_time.counts_as_activity(page) is False, "the import day is not when the page was said"
    assert row["source"] == "notion-export" and episode_time.counts_as_activity(row) is True
    bank_index.invalidate()
    assert eps[f"notion:{ROOT_ID}"][0].stem in episode_time.untimed_ids(memory)


def _untitled_export(rows_order):
    u1, u2 = "e" * 31 + "1", "e" * 31 + "2"
    page1 = "# Untitled\n\nStatus: Idea\nCreated: March 1, 2024 9:00 AM\n\nfirst body\n"
    page2 = "# Untitled\n\nStatus: Done\nCreated: June 2, 2025 9:00 AM\n\nsecond body\n"
    lines = {"1": "Untitled,Idea,\"March 1, 2024 9:00 AM\"", "2": "Untitled,Done,\"June 2, 2025 9:00 AM\""}
    csv_text = "Name,Status,Created\n" + "\n".join(lines[k] for k in rows_order) + "\n"
    return _zip({f"Ideas {IDEAS_ID}.csv": csv_text,
                 f"Ideas {IDEAS_ID}/Untitled {u1}.md": page1,
                 f"Ideas {IDEAS_ID}/Untitled {u2}.md": page2}), u1, u2


@pytest.mark.parametrize("order", [("1", "2"), ("2", "1")])
def test_b3_same_title_rows_keep_their_own_properties_in_either_csv_order(order):
    data, u1, u2 = _untitled_export(order)
    parsed = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(data)))
    by_id = {e["source_id"]: e for e in parsed.episodes}
    first, second = by_id[f"notion:{u1}"], by_id[f"notion:{u2}"]
    assert "**Status:** Idea" in first["body"] and "first body" in first["body"]
    assert first["original_date"] == "2024-03-01"
    assert "**Status:** Done" in second["body"] and "second body" in second["body"]
    assert second["original_date"] == "2025-06-02"


def test_a_row_another_person_created_is_their_words():
    data = _zip({f"Ideas {IDEAS_ID}.csv": "Name,Status,Created by\nMine,Idea,Verify Person\nTheirs,Idea,Bob Example\n"})
    with_owner = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(data)), ("Verify Person",))
    kinds = {e["title"]: e["extra"]["evidence_kind"] for e in with_owner.episodes}
    assert kinds == {"Mine": "user", "Theirs": "assistant"}
    assert with_owner.by_others == 1 and any("created by someone else" in w for w in with_owner.warnings)
    # No owner name known: a table more than one person wrote is never credited to the person on a guess.
    unknown = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(data)))
    assert {e["extra"]["evidence_kind"] for e in unknown.episodes} == {"assistant"}
    # One author and no owner known: the person's own export, their words.
    solo = notion_export.parse_zip(zipfile.ZipFile(io.BytesIO(_zip({
        f"Ideas {IDEAS_ID}.csv": "Name,Created by\nA,Someone\nB,Someone\n"}))))
    assert {e["extra"]["evidence_kind"] for e in solo.episodes} == {"user"}
