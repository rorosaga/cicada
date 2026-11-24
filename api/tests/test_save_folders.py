"""G221 (owner 2026-11-23) — the folders a platform's own save is filed in, and one reason the person may give a
whole folder.

A save can sit in several folders and any door that sees it reports them, on that one save, in place. A folder is a
filing label: the existing ``folder`` field (what ``history_index.kind`` reads) is untouched. A folder's reason is the
person's own words about the folder; a save with none of its own inherits it, marked as the folder's, and that makes the
save readable by Sleep — counted first, never silently. Synthetic posts, placeholder names only."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from _reading_fixtures import reading  # noqa: F401 — a fixture
from api.services import history_index, markdown_parser, reading_settings, saved_why, save_folders

from api.tests.test_saved_why import _bank, _client, _offline  # noqa: F401 — the offline fixture and scratch banks

POST_A = "https://x.com/alpha_user/status/1900000000000000001"
POST_B = "https://x.com/alpha_user/status/1900000000000000002"
POST_C = "https://x.com/alpha_user/status/1900000000000000003"


def _episode(memory: Path, episode_id: str) -> dict:
    return markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").frontmatter


def _save(client, url, **body):
    r = client.post("/sources/site-save", json={"site": "x", "url": url, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _reason(client, folder="Design refs", **body):
    return client.post("/sources/save-folder-reason", json={"site": "x", "folder": folder, **body})


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


# ---- a save in several folders ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _saves_wait_their_turn(monkeypatch):
    """These tests are about the pile (ruling 80): saves that wait their turn, which a folder's reason brings back for a
    read. Capture's own placement (a click waits for tonight, a post with no words has nothing to read) is
    ``test_saves_read_g246.py``'s."""
    real = history_index.entry_stamp
    monkeypatch.setattr(history_index, "entry_stamp", lambda fm, **kw: real(fm, **{**kw, "bulk": True, "walled": False}))


def test_a_save_reports_its_folders_and_the_fixed_label_stays_what_index_only_reads(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    saved = _save(client, POST_A, folders=["Design refs", "  Recipes  ", "design REFS", ""])
    assert saved["folders"] == ["Design refs", "Recipes"] and saved["reason"] is None
    fm = _episode(memory, saved["episodeId"])
    assert fm["save_folders"] == {"x-bookmarks": ["Design refs", "Recipes"]}
    # The platform's own label is what ruling 62's index-only rule keys on, and it did not move.
    assert fm["folder"] == "Bookmarks" and history_index.kind(fm) == "list" and fm["processed_by"] == "index"
    # A folder is a label: no page, no claim, no second episode.
    assert len(list((memory / "episodes").glob("*.md"))) == 1
    assert not [p for p in (memory / "entities").glob("*.md") if "design" in p.name]


def test_filing_a_saved_post_later_is_a_change_to_that_save_never_a_second_one(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    first = _save(client, POST_A, folders=["Design refs"])
    again = _save(client, POST_A + "?s=46", folders=["Recipes"])
    assert again["status"] == "duplicate" and again["episodeId"] == first["episodeId"]
    assert again["folders"] == ["Design refs", "Recipes"]
    assert len(list((memory / "episodes").glob("*.md"))) == 1
    # Taken out of one; the same report again changes nothing.
    gone = _save(client, POST_A, removeFolders=["design refs"], folders=["Recipes"])
    assert gone["folders"] == ["Recipes"]
    assert _episode(memory, first["episodeId"])["save_folders"] == {"x-bookmarks": ["Recipes"]}
    last = _save(client, POST_A, removeFolders=["Recipes"])
    assert last["folders"] == [] and "save_folders" not in _episode(memory, first["episodeId"])


def test_the_list_of_a_sites_folders_counts_saves_and_what_a_reason_would_make_readable(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    _save(client, POST_A, folders=["Design refs", "Recipes"])
    _save(client, POST_B, folders=["Design refs"])
    _save(client, POST_C)
    assert _reason(client, "Empty folder", text="nothing in it yet").status_code == 200
    body = client.get("/sources/save-folders", params={"site": "x"}).json()
    rows = {r["name"]: r for r in body["folders"]}
    assert (body["origin"], body["saves"], body["unfiled"]) == ("x-bookmarks", 3, 1)
    assert (rows["Design refs"]["saves"], rows["Design refs"]["indexOnly"]) == (2, 2)
    assert rows["Recipes"]["reason"] is None and rows["Empty folder"]["saves"] == 0
    assert rows["Empty folder"]["reason"]["text"] == "nothing in it yet"
    assert client.get("/sources/save-folders", params={"site": "no-such"}).status_code == 422


# ---- a folder's reason -----------------------------------------------------------------------------------------------


def test_a_folders_reason_counts_before_it_writes_and_a_dry_run_writes_nothing(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    _save(client, POST_B, folders=["Design refs"])
    r = _reason(client, reasons=["design"], text="type specimens", dryRun=True)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is False and r.json()["counts"]["makesReadable"] == 2
    assert not (memory / save_folders.STORE).exists()
    assert _episode(memory, a["episodeId"])["processed_by"] == "index"
    # An empty answer names nothing: refused as a save's own is.
    assert _reason(client).status_code == 422 and _reason(client, reasons=["no-such-key"]).status_code == 422
    assert client.post("/sources/save-folder-reason", json={"site": "no-such", "folder": "x", "text": "a"}).status_code == 422


def test_a_reason_makes_the_saves_in_the_folder_readable_and_says_whose_reason_it_is(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=True)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    other = _save(client, POST_B, folders=["Recipes"])
    r = _reason(client, reasons=["design"], text="type specimens for the logo")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["applied"] is True and out["counts"] == {"saves": 1, "makesReadable": 1, "alreadyReadable": 0,
                                                         "noLongerReadable": 0}
    assert out["reason"]["labels"] == ["The design"] and out["reason"]["text"] == "type specimens for the logo"
    # Readable: no longer index-only, queued for Sleep; the one in another folder is untouched.
    fm = _episode(memory, a["episodeId"])
    assert history_index.kind(fm) is None and fm["processed"] is False and "processed_by" not in fm
    assert fm["readable_by_folder"]["folders"] == ["Design refs"] and not fm.get("saved_why")
    assert history_index.waits_for_model(fm)
    assert history_index.kind(_episode(memory, other["episodeId"])) == "list"
    # Inherited by the one reader every consumer uses, and marked as the folder's.
    reason = saved_why.reason_of(memory, [a["episodeId"]])
    assert reason.inherited_from == ("Design refs",)
    assert reason.text.startswith('From its folder "Design refs":') and "type specimens" in reason.text
    assert saved_why.reason_of(memory, [other["episodeId"]]) is None
    # Committed alone, as the person.
    log = _git(memory, "log", "-1", "--format=%B", "--name-only")
    assert "Cicada-Author: user" in log and "sources/folder_reasons.json" in log and f"{a['episodeId']}.md" in log
    assert _git(memory, "status", "--porcelain").strip() == ""
    # The same words again change nothing (no new commit).
    head = _git(memory, "rev-parse", "HEAD")
    assert _reason(client, reasons=["design"], text="type specimens for the logo").json()["changed"] is False
    assert _git(memory, "rev-parse", "HEAD") == head


def test_the_saves_own_reason_always_wins_and_is_never_shown_as_the_folders(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    _reason(client, reasons=["design"])
    own = client.post("/sources/saved-why", json={"url": a["url"], "reasons": ["read_later"], "text": "for the sync idea"})
    assert own.status_code == 200, own.text
    reason = saved_why.reason_of(memory, [a["episodeId"]])
    assert reason.inherited_from == () and "To read later" in reason.text and "From its folder" not in reason.text
    # A post saved again now is told the person already has a reason for it.
    assert _save(client, POST_A)["reason"] == "own"
    # On the wire the answer about the save stays in savedWhy; the folder's rides apart, always marked.
    item = next(i for i in client.get("/sources").json()["items"] if i["url"] == a["url"])
    assert item["savedWhy"]["text"] == "for the sync idea"
    assert item["saveFolders"] == [{"origin": "x-bookmarks", "name": "Design refs"}]
    assert item["folderWhy"][0]["folder"] == "Design refs" and item["folderWhy"][0]["inherited"] is True


def test_a_folder_only_reason_rides_folder_why_never_saved_why_on_the_wire(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    etag = client.get("/sources").headers["etag"]
    _reason(client, reasons=["design"], text="type specimens")
    res = client.get("/sources")
    assert res.headers["etag"] != etag
    item = next(i for i in res.json()["items"] if i["url"] == a["url"])
    assert item["savedWhy"] is None and item["savedWhyHistory"] == []
    assert item["folderWhy"] == [{**item["folderWhy"][0], "labels": ["The design"], "text": "type specimens",
                                  "inherited": True}]
    assert _save(client, POST_A)["reason"] == "folder"


def test_editing_keeps_the_earlier_words_and_clearing_returns_unread_saves_to_the_index(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    _reason(client, text="first words")
    edited = client.put("/sources/save-folder-reason", json={"site": "x", "folder": "design refs", "text": "better words"}).json()
    assert edited["changed"] is True and edited["folder"] == "Design refs"
    assert edited["reason"]["editedAt"] and edited["reason"]["before"][0]["text"] == "first words"
    assert edited["counts"]["makesReadable"] == 0      # already readable: an edit queues nothing more
    cleared = client.delete("/sources/save-folder-reason", params={"site": "x", "folder": "Design refs"})
    assert cleared.status_code == 200 and cleared.json()["counts"]["noLongerReadable"] == 1
    fm = _episode(memory, a["episodeId"])
    # Ruling 80: the reason's words are gone, the save stays what it is — a save, read tonight as its author's words.
    assert "readable_by_folder" not in fm and history_index.save_state(fm) == "waiting"
    assert saved_why.reason_of(memory, [a["episodeId"]]) is None
    assert history_index.retire(memory).paths == []
    assert client.delete("/sources/save-folder-reason", params={"site": "x", "folder": "Design refs"}).status_code == 404


def test_a_save_filed_later_into_a_folder_that_has_a_reason_is_readable_at_once(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A)
    _reason(client, reasons=["design"])           # a folder with no saves yet
    filed = _save(client, POST_A, folders=["Design refs"])
    assert filed["episodeId"] == a["episodeId"] and filed["reason"] == "folder"
    fm = _episode(memory, a["episodeId"])
    assert history_index.kind(fm) is None and fm["processed"] is False
    # Taken out of the folder again: no stamp; the index takes it back.
    _save(client, POST_A, removeFolders=["Design refs"])
    assert "readable_by_folder" not in _episode(memory, a["episodeId"])


def test_a_save_a_model_already_read_is_never_requeued_by_a_folders_reason(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    path = memory / "episodes" / f"{a['episodeId']}.md"
    parsed = markdown_parser.parse(path)
    fm = {**parsed.frontmatter, "processed": True, "processed_by": "claude-code", "origin": "chrome-bookmark"}
    markdown_parser.write(path, fm, parsed.body)
    out = _reason(client, reasons=["design"]).json()
    assert out["counts"]["makesReadable"] == 0
    assert "readable_by_folder" not in _episode(memory, a["episodeId"])


def test_a_big_folder_needs_the_callers_confirm_before_anything_is_written(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    ids = [_save(client, u, folders=["Design refs"])["episodeId"] for u in (POST_A, POST_B, POST_C)]
    monkeypatch.setattr(save_folders, "CONFIRM_ABOVE", 2)
    held = _reason(client, reasons=["design"]).json()
    assert held["needsConfirm"] is True and held["applied"] is False and held["counts"]["makesReadable"] == 3
    assert not (memory / save_folders.STORE).exists()
    assert all(_episode(memory, i)["processed_by"] == "index" for i in ids)
    done = _reason(client, reasons=["design"], confirm=True).json()
    assert done["applied"] is True and done["counts"]["makesReadable"] == 3
    assert all(history_index.kind(_episode(memory, i)) is None for i in ids)


def test_a_folders_reason_is_scrubbed_like_every_writer(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0"
    out = _reason(client, text=f"for the build, key {secret}").json()
    assert secret not in out["reason"]["text"]
    assert secret not in (memory / save_folders.STORE).read_text()
    assert save_folders.clean_name(f"board {secret}") == "board [redacted]"


# ---- the person's agent reports a list with folders -------------------------------------------------------------------


def test_a_saved_list_read_files_each_post_in_its_folders_and_a_post_saved_before_is_filed_not_saved_again(reading):
    from api.services import media_ingestor

    server, memory = reading
    reading_settings.update(saved_lists_={"x": True})

    def record(items):
        return server.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": items})

    assert "1 new post(s) saved" in record([{"url": POST_A, "text": "alpha words", "folders": ["Design refs"]}])
    out = record([{"url": POST_A, "folders": ["Recipes", "Design refs"]}, {"url": POST_B}])
    assert "1 new post(s) saved; 1 already in memory" in out
    idx = media_ingestor.load_url_index(memory)
    episode = idx[media_ingestor.url_hash(POST_A)]["episode_id"]
    fm = _episode(memory, episode)
    assert fm["save_folders"] == {"x-bookmarks": ["Design refs", "Recipes"]}
    assert fm["folder"] == "Bookmarks" and history_index.kind(fm) == "list"
    assert sum(1 for f in (memory / "episodes").glob("*.md") if _episode(memory, f.stem).get("origin") == "x-bookmarks") == 2
    assert "readable_by_folder" not in _episode(memory, idx[media_ingestor.url_hash(POST_B)]["episode_id"])


def test_the_tool_schema_takes_folders_on_a_row(reading):
    stdio, _ = reading
    props = next(t for t in stdio.TOOLS if t["name"] == "cicada_record_saved_list")["inputSchema"]["properties"]
    assert props["items"]["items"]["properties"]["folders"]["items"] == {"type": "string"}


# ---- the readers --------------------------------------------------------------------------------------------------


def test_explore_and_the_reading_queue_see_an_inherited_reason_marked_as_the_folders(tmp_path, monkeypatch):
    from api.services import explore_candidates, explore_plan

    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    a = _save(client, POST_A, folders=["Design refs"])
    _reason(client, reasons=["design"], text="type specimens")
    site = next(s for s in explore_candidates.saved_sites(memory, include_excluded=True).values() if s.url == a["url"])
    assert site.why["inherited_from"] == ["Design refs"] and "design" in site.why["reasons"]
    plan = explore_plan.plan_for(site.why)
    assert {"from": "folder", "signal": "design"} in plan["because"]
    # A site's row on the Sources channel shows it marked.
    from api.services import channel_items

    assert channel_items._why(memory, a["episodeId"])["fromFolders"] == ["Design refs"]
