"""G161 — what came in, by name: `channel_items.items` and `GET /sources/channels/{id}/items`.

Every test builds a synthetic bank under tmp_path; nothing real is read.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_items


def _write(path, fm: dict, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines += ["---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8")


def _episode(bank, ep_id, **fm):
    _write(bank / "episodes" / f"{ep_id}.md", {"id": ep_id, "processed": False, **fm},
           "BODY TEXT THAT MUST NEVER TRAVEL")


def _page(bank, entity_id, **fm):
    _write(bank / "entities" / f"{entity_id}.md", {"id": entity_id, "status": "active", **fm},
           "PAGE BODY THAT MUST NEVER TRAVEL")


def _json(bank, rel, data):
    path = bank / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_words_index(monkeypatch):
    """A search here matches titles alone unless a test says what the words index answers (its own behaviour is
    `test_search_index`'s): no index is built in the background of a list test."""
    from api.services import search_index

    monkeypatch.setattr(search_index, "episodes_with_words", lambda memory_path, q: None)


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "memory"
    b.mkdir()
    # Apple Notes: two notes in the index (one edited, so two episodes — only the latest is listed).
    _episode(b, "ep_2026-09-01_001", title="Garden plan", origin="apple-notes", timestamp="2026-09-01T08:00:00+00:00")
    _episode(b, "ep_2026-09-02_001", title="Reading list", origin="apple-notes", timestamp="2026-09-02T08:00:00+00:00")
    _episode(b, "ep_2026-09-03_001", title="Reading list", origin="apple-notes", timestamp="2026-09-03T08:00:00+00:00")
    _json(b, "sources/notes_index.json", {
        "n1": {"episode_id": "ep_2026-09-01_001", "modified": "a", "note_id": "n1"},
        "n2": {"episode_id": "ep_2026-09-03_001", "modified": "b", "note_id": "n2"},
    })
    # Calendar on this Mac: two live events and a tombstoned one; the day is the event's own.
    _episode(b, "ep_2026-09-04_001", title="Standup", origin="calendar-local", source_id="calendar-local:e1",
             timestamp="2026-09-04T08:00:00+00:00", event_start="2026-10-01T09:00:00-05:00")
    _episode(b, "ep_2026-09-04_002", title="Dentist", origin="calendar-local", source_id="calendar-local:e2",
             timestamp="2026-09-04T08:00:00+00:00", event_start="2026-09-20T15:00:00+00:00")
    _episode(b, "ep_2026-09-04_003", title="Cancelled thing", origin="calendar-local",
             source_id="calendar-local:e3", timestamp="2026-09-04T08:00:00+00:00",
             event_start="2026-09-21T15:00:00+00:00", source_deleted_at="2026-09-05T00:00:00+00:00")
    # Chrome's tab groups: one live, one closed.
    _episode(b, "ep_2026-09-05_001", title="Tab group: Research", origin="chrome-tab-group",
             source_id="tab-group:chrome:Default:named:abc", timestamp="2026-09-05T08:00:00+00:00")
    _episode(b, "ep_2026-09-05_002", title="Tab group: Old", origin="chrome-tab-group",
             source_id="tab-group:chrome:Default:named:def", timestamp="2026-09-05T09:00:00+00:00",
             source_deleted_at="2026-09-06T00:00:00+00:00")
    # Contacts: one matched page (facts), one matched by photo only, one person Contacts never touched.
    _page(b, "bob-example", type="person", name="Bob Example", sources=[
        {"ref": "addressbook://ABC-123", "kind": "app", "predicate": "email", "added_by": "cicada",
         "added_at": "2026-09-07"}])
    _page(b, "carol-example", type="person", name="Carol Example", contacts_photo={"sha": "x", "ext": "jpg"})
    _page(b, "dave-example", type="person", name="Dave Example")
    # Bookmarks: three media pages; the browser last saw two of them (the third was removed there).
    _page(b, "media-one", type="media", name="One page", origin="chrome-bookmark", created="2026-09-01")
    _page(b, "media-two", type="media", name="Two page", origin="chrome-bookmark", created="2026-09-02")
    _page(b, "media-gone", type="media", name="Gone page", origin="chrome-bookmark", created="2026-09-03")
    _json(b, "sources/url_index.json", {
        "h1": {"media_entity_id": "media-one", "title": "One", "url": "https://example.com/1",
               "saved_at": "2026-09-01T10:00:00+00:00"},
        "h2": {"media_entity_id": "media-two", "title": "Two", "url": "https://example.com/2",
               "saved_at": "2026-09-02T10:00:00+00:00", "content_saved_at": "2026-08-01"},
        "h3": {"media_entity_id": "media-gone", "title": "Gone", "url": "https://example.com/3",
               "saved_at": "2026-09-03T10:00:00+00:00"},
        "h9": {"media_entity_id": "media-link", "title": "A link", "url": "https://example.com/9",
               "saved_at": "2026-09-09T10:00:00+00:00"},
        "h10": {"media_entity_id": "media-tg", "title": "Telegram link", "url": "https://example.com/10",
                "saved_at": "2026-09-10T10:00:00+00:00"},
    })
    _json(b, "sources/bookmark_seen.json", {"chrome-bookmarks": {"folders": None, "hashes": ["h1", "h2"],
                                                                "at": "2026-09-08T00:00:00Z"}})
    # Pinterest: one live pin, one archived (the Feed hides it, so the list does).
    _page(b, "media-pin", type="media", name="A pin", origin="pinterest", created="2026-09-06")
    _page(b, "media-pin-archived", type="media", name="Old pin", origin="pinterest", created="2026-09-06",
          status="archived")
    # Files & links: a stamped save and an unstamped legacy page.
    _page(b, "media-link", type="media", name="A link", origin="saved-link", created="2026-09-09")
    _page(b, "media-legacy", type="media", name="Legacy link", created="2026-08-01")
    # A Claude export: two conversations, dated by the export.
    _episode(b, "ep_2026-09-10_001", title="Planning chat", origin="claude-export", original_date="2026-05-01",
             timestamp="2026-09-10T08:00:00+00:00")
    _episode(b, "ep_2026-09-10_002", title="Another chat", origin="claude-export", original_date="2026-06-01",
             timestamp="2026-09-10T08:00:00+00:00")
    # Telegram: a text capture, and a saved link whose capture episode is listed as its page.
    _episode(b, "ep_2026-09-10_003", title="A thought", origin="telegram", timestamp="2026-09-10T09:00:00+00:00")
    _episode(b, "ep_2026-09-10_004", title="Telegram link", origin="telegram", media_entity_id="media-tg",
             timestamp="2026-09-10T10:00:00+00:00")
    _page(b, "media-tg", type="media", name="Telegram link", origin="telegram", created="2026-09-10")
    # A watched folder with one note, and an episode of another folder.
    _json(b, "sources/folders.json", {"folders": [{"id": "f1", "label": "Notes folder"}]})
    _episode(b, "ep_2026-09-11_001", title="Notes folder › ideas/garden.md › Intro", origin="folder", folder_id="f1",
             relpath="ideas/garden.md", source_id="folder:f1:ideas/garden.md#intro",
             timestamp="2026-09-11T08:00:00+00:00", original_date="2026-09-11")
    _episode(b, "ep_2026-09-11_003", title="Notes folder › ideas/garden.md › Beds", origin="folder", folder_id="f1",
             relpath="ideas/garden.md", source_id="folder:f1:ideas/garden.md#beds",
             timestamp="2026-09-11T08:00:00+00:00", original_date="2026-09-11")
    _episode(b, "ep_2026-09-11_002", title="other.md", origin="folder", folder_id="f2",
             timestamp="2026-09-11T08:00:00+00:00")
    # Wispr Flow.
    _episode(b, "ep_2026-09-12_001", title="Meeting with a secret sk-ant-api03-" + "A" * 40, origin="wispr-flow",
             original_date="2026-09-12", timestamp="2026-09-12T08:00:00+00:00")
    bank_index.invalidate()
    return b


def _ids(page):
    return [row["id"] for row in page["items"]]


def test_notes_lists_the_latest_episode_per_note(bank):
    page = channel_items.items(bank, "notes")
    assert page["total"] == 2
    assert _ids(page) == ["ep_2026-09-03_001", "ep_2026-09-01_001"]
    assert page["items"][0] == {"kind": "episode", "id": "ep_2026-09-03_001", "title": "Reading list",
                                "day": "2026-09-03"}


def test_calendar_is_newest_first_by_the_events_own_day_and_skips_tombstones(bank):
    page = channel_items.items(bank, "calendar-local")
    assert _ids(page) == ["ep_2026-09-04_001", "ep_2026-09-04_002"]
    assert page["items"][0]["day"] == "2026-10-01", "the event's own calendar day, never shifted to UTC"


def test_tab_groups_skip_a_closed_group(bank):
    page = channel_items.items(bank, "chrome-tab-groups")
    assert _ids(page) == ["ep_2026-09-05_001"]
    assert page["items"][0]["title"] == "Tab group: Research"


def test_contacts_shows_the_matched_pages_names_only(bank):
    page = channel_items.items(bank, "contacts-local")
    assert {r["id"] for r in page["items"]} == {"bob-example", "carol-example"}
    wire = json.dumps(page)
    assert "addressbook" not in wire and "ABC-123" not in wire, "never the address-book id"
    assert "email" not in wire, "never which facts the card holds"
    bob = next(r for r in page["items"] if r["id"] == "bob-example")
    assert bob == {"kind": "page", "id": "bob-example", "title": "Bob Example", "day": "2026-09-07"}


def test_bookmarks_list_what_the_browser_last_showed(bank):
    page = channel_items.items(bank, "chrome-bookmarks")
    assert _ids(page) == ["media-one", "media-two"], "newest saved first; the one removed from Chrome is gone"
    assert page["items"][1]["day"] == "2026-08-01", "the browser's own save date wins"
    assert all(r["kind"] == "media" for r in page["items"])


def test_bookmarks_without_a_seen_set_fall_back_to_the_browsers_pages(bank):
    (bank / "sources" / "bookmark_seen.json").unlink()
    bank_index.invalidate()
    assert set(_ids(channel_items.items(bank, "chrome-bookmarks"))) == {"media-one", "media-two", "media-gone"}


def test_media_channels_hide_what_the_feed_hides(bank):
    assert _ids(channel_items.items(bank, "pinterest")) == ["media-pin"]
    assert set(_ids(channel_items.items(bank, "files"))) == {"media-link", "media-legacy"}


def test_chat_export_is_dated_by_the_export(bank):
    page = channel_items.items(bank, "chat-export:claude")
    assert _ids(page) == ["ep_2026-09-10_002", "ep_2026-09-10_001"]
    assert [r["day"] for r in page["items"]] == ["2026-06-01", "2026-05-01"]


def test_telegram_lists_a_saved_link_as_its_page(bank):
    page = channel_items.items(bank, "telegram")
    assert [(r["kind"], r["id"]) for r in page["items"]] == [("media", "media-tg"), ("episode", "ep_2026-09-10_003")]


def test_a_folder_lists_its_own_episodes(bank):
    page = channel_items.items(bank, "folder:f1")
    assert page["items"] == [{"kind": "episode", "id": "ep_2026-09-11_001", "title": "garden", "day": "2026-09-11"}], \
        "one row per file, by its own name, opening at its first section"
    assert channel_items.items(bank, "folder:f2") is None, "an unregistered folder is not a channel"


def test_titles_are_scrubbed_and_bodies_never_travel(bank):
    page = channel_items.items(bank, "wispr-flow")
    assert "sk-ant" not in page["items"][0]["title"]
    for cid in ("notes", "calendar-local", "chrome-tab-groups", "wispr-flow", "chrome-bookmarks", "telegram"):
        wire = json.dumps(channel_items.items(bank, cid))
        assert "MUST NEVER TRAVEL" not in wire


def test_a_long_title_is_cut_to_one_line(bank):
    _episode(bank, "ep_2026-09-13_001", title="word " * 80 + "\nsecond line", origin="wispr-flow",
             timestamp="2026-09-13T08:00:00+00:00")
    bank_index.invalidate()
    title = channel_items.items(bank, "wispr-flow")["items"][0]["title"]
    assert len(title) <= channel_items.TITLE_CAP and "\n" not in title and title.endswith("…")


def test_paging(bank):
    first = channel_items.items(bank, "notes", offset=0, limit=1)
    second = channel_items.items(bank, "notes", offset=1, limit=1)
    assert first["total"] == second["total"] == 2
    assert _ids(first) + _ids(second) == ["ep_2026-09-03_001", "ep_2026-09-01_001"]
    assert channel_items.items(bank, "notes", offset=5)["items"] == []
    assert channel_items.items(bank, "notes", limit=10_000)["limit"] == channel_items.LIMIT_MAX


def test_an_unknown_channel_is_none_and_an_empty_known_one_is_empty(bank):
    assert channel_items.items(bank, "nope") is None
    assert channel_items.items(bank, "reddit") == {"channel": "reddit", "total": 0, "all": 0, "latest": None,
                                                   "offset": 0, "limit": channel_items.LIMIT_DEFAULT, "items": []}


def test_every_listed_channel_is_known(bank):
    from api.services import channel_registry

    for channel in channel_registry.build_channels(bank, telegram_enabled=False):
        assert channel_items.known(bank, channel["id"]), channel["id"]


# --- the route ------------------------------------------------------------------


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(bank.parent / "home"))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_route_answers_a_page_and_304s_on_its_etag(client):
    first = client.get("/sources/channels/notes/items", params={"limit": 1})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["channel"] == "notes" and body["total"] == 2 and len(body["items"]) == 1
    etag = first.headers["etag"]
    again = client.get("/sources/channels/notes/items", params={"limit": 1}, headers={"If-None-Match": etag})
    assert again.status_code == 304
    other = client.get("/sources/channels/notes/items", params={"limit": 1, "offset": 1},
                       headers={"If-None-Match": etag})
    assert other.status_code == 200, "another page is another tag"


def test_route_accepts_a_colon_in_the_channel_id(client):
    response = client.get("/sources/channels/chat-export:claude/items")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_route_404s_an_unknown_channel_and_refuses_a_page_past_the_cap(client):
    assert client.get("/sources/channels/nope/items").status_code == 404
    assert client.get("/sources/channels/notes/items", params={"limit": 201}).status_code == 422


def test_route_etag_moves_when_the_bank_does(client, bank):
    first = client.get("/sources/channels/wispr-flow/items")
    _episode(bank, "ep_2026-09-14_001", title="New capture", origin="wispr-flow",
             timestamp="2026-09-14T08:00:00+00:00")
    second = client.get("/sources/channels/wispr-flow/items", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 200
    assert second.json()["items"][0]["title"] == "New capture"


# --- Sources v3: a saved link's site and why (owner 2026-10-19) -------------------------------------------------


def _with_why(bank):
    """`media-one`'s link carries two answers (the newest wins); `media-two` none."""
    entries = json.loads((bank / "sources" / "url_index.json").read_text())
    entries["h1"]["episode_id"] = "ep_2026-09-01_101"
    entries["h1"]["url"] = "https://www.example.com/1?utm=secret"
    entries["h2"]["episode_id"] = "ep_2026-09-02_101"
    _json(bank, "sources/url_index.json", entries)
    _episode(bank, "ep_2026-09-01_101", title="One", origin="chrome-bookmark", media_entity_id="media-one",
             timestamp="2026-09-01T10:00:00+00:00",
             saved_why_earlier=[{"reasons": ["read_later"], "text": "older words", "at": "2026-09-01T10:00:05+00:00"}],
             saved_why={"reasons": ["design", "technique"], "text": "the   layout\nof the hero", "project": None,
                        "at": "2026-09-05T10:00:05+00:00"})
    _episode(bank, "ep_2026-09-02_101", title="Two", origin="chrome-bookmark", media_entity_id="media-two",
             timestamp="2026-09-02T10:00:00+00:00")
    bank_index.invalidate()


def test_a_saved_link_row_names_its_site_and_the_newest_why(bank):
    _with_why(bank)
    rows = {r["id"]: r for r in channel_items.items(bank, "chrome-bookmarks")["items"]}
    one = rows["media-one"]
    assert one["host"] == "example.com", "the bare host, www. dropped — never the URL, path or query"
    assert one["site"] == "example.com", "the key its mark is asked under"
    assert "utm" not in json.dumps(one) and "https" not in json.dumps(one)
    assert one["why"] == {"labels": ["The design", "A technique to reuse"], "text": "the layout of the hero"}, \
        "the newest answer, retired reasons still read, words on one line"
    assert "why" not in rows["media-two"], "no answer, no why"
    assert rows["media-two"]["host"] == "example.com"


def test_a_long_why_is_cut_to_one_line(bank):
    _with_why(bank)
    path = bank / "episodes" / "ep_2026-09-01_101.md"
    _write(path, {"id": "ep_2026-09-01_101", "saved_why": {"reasons": [], "text": "word " * 100,
                                                            "at": "2026-09-05T10:00:05+00:00"}})
    bank_index.invalidate()
    one = next(r for r in channel_items.items(bank, "chrome-bookmarks")["items"] if r["id"] == "media-one")
    assert len(one["why"]["text"]) <= channel_items.WHY_CAP and one["why"]["text"].endswith("…")
    assert one["why"]["labels"] == []


def test_only_the_page_served_is_read_for_its_why(bank, monkeypatch):
    _with_why(bank)
    asked = []
    real = bank_index.file

    def spy(memory_path, subdir, name):
        asked.append(name)
        return real(memory_path, subdir, name)

    monkeypatch.setattr(channel_items.bank_index, "file", spy)
    page = channel_items.items(bank, "chrome-bookmarks", limit=1)
    assert _ids(page) == ["media-one"] and asked == ["ep_2026-09-01_101.md"], "the second row's episode is never read"


def test_episode_and_page_rows_carry_no_site_or_why(bank):
    for row in channel_items.items(bank, "notes")["items"] + channel_items.items(bank, "contacts-local")["items"]:
        assert "site" not in row and "host" not in row and "why" not in row


def test_a_saved_source_without_a_channel_lists_by_its_row_id(bank):
    _page(bank, "media-ig", type="media", name="A saved post", origin="instagram-saved", created="2026-09-06")
    _page(bank, "media-yt", type="media", name="A video", origin="youtube-playlist", created="2026-09-07")
    bank_index.invalidate()
    assert channel_items.known(bank, "instagram") and channel_items.known(bank, "youtube")
    assert _ids(channel_items.items(bank, "instagram")) == ["media-ig"]
    assert _ids(channel_items.items(bank, "youtube")) == ["media-yt"]
    assert not channel_items.known(bank, "harness:claude-code"), "a captured source is not a saved list"


def test_a_walled_sites_mark_is_asked_under_its_family_name(bank):
    entries = json.loads((bank / "sources" / "url_index.json").read_text())
    entries["h1"]["url"] = "https://www.linkedin.com/posts/someone-123"
    _json(bank, "sources/url_index.json", entries)
    bank_index.invalidate()
    one = next(r for r in channel_items.items(bank, "chrome-bookmarks")["items"] if r["id"] == "media-one")
    assert one["host"] == "linkedin.com" and one["site"] == "linkedin"
    assert "someone" not in json.dumps(one)


# --- source-page-v3: one search, and the day the newest item came in ---------------------------------------------


def test_latest_is_the_day_the_newest_item_came_in_whatever_q_says(bank):
    page = channel_items.items(bank, "notes")
    assert page["latest"] == "2026-09-03" and page["all"] == 2
    assert channel_items.items(bank, "notes", q="garden")["latest"] == "2026-09-03"


def test_latest_counts_the_day_an_old_item_was_received(bank):
    """Ruling 39: history read today says today, not the item's own months-old day."""
    _episode(bank, "ep_2026-09-13_001", title="Old chat", origin="claude-export", original_date="2026-01-01",
             timestamp="2026-09-13T08:00:00+00:00", received_at="2026-09-13T08:00:00+00:00")
    bank_index.invalidate()
    assert channel_items.items(bank, "chat-export:claude")["latest"] == "2026-09-13"


def test_q_matches_titles_folded_and_every_word(bank):
    page = channel_items.items(bank, "notes", q="  READING ")
    assert _ids(page) == ["ep_2026-09-03_001"] and page["total"] == 1 and page["all"] == 2
    assert channel_items.items(bank, "notes", q="reading garden")["total"] == 0, "every word must match"
    assert channel_items.items(bank, "notes", q="")["total"] == 2, "an empty search is no search"


def test_q_matches_a_saved_links_host_never_its_path(bank):
    assert channel_items.items(bank, "chrome-bookmarks", q="example.com")["total"] == 2
    assert channel_items.items(bank, "chrome-bookmarks", q="/1")["total"] == 0


def test_q_widens_with_the_words_index_where_it_answers(bank, monkeypatch):
    from api.services import search_index

    monkeypatch.setattr(search_index, "episodes_with_words", lambda memory_path, q: {"ep_2026-09-01_001"})
    page = channel_items.items(bank, "notes", q="tomatoes")
    assert _ids(page) == ["ep_2026-09-01_001"], "a note whose words match is found though its title does not"


def test_q_finds_a_chat_by_a_sitting_that_matched(bank, monkeypatch):
    from api.services import search_index

    chat = "a" * 32
    for n, day in ((1, "2026-09-14"), (2, "2026-09-15")):
        _episode(bank, f"ep_{day}_00{n}", title=f"Messages with Person A · {day}", origin="imessage",
                 conversation=chat, correspondent={"name": "Person A"}, timestamp=f"{day}T08:00:00+00:00")
    bank_index.invalidate()
    monkeypatch.setattr(search_index, "episodes_with_words", lambda memory_path, q: {"ep_2026-09-14_001"})
    rows = channel_items.items(bank, "imessage", q="thursday")["items"]
    assert [r["id"] for r in rows] == [chat]
    monkeypatch.setattr(search_index, "episodes_with_words", lambda memory_path, q: set())
    assert channel_items.items(bank, "imessage", q="person a")["total"] == 1, "a chat is found by its name"
    assert channel_items.items(bank, "imessage", q="thursday")["total"] == 0


def test_q_with_no_words_index_matches_titles_alone(bank, monkeypatch):
    from api.services import search_index

    monkeypatch.setattr(search_index, "episodes_with_words", lambda memory_path, q: None)
    assert _ids(channel_items.items(bank, "notes", q="garden")) == ["ep_2026-09-01_001"]


def test_route_takes_q_and_tags_each_search_apart(client):
    first = client.get("/sources/channels/notes/items", params={"q": "garden"})
    assert first.status_code == 200, first.text
    assert [r["id"] for r in first.json()["items"]] == ["ep_2026-09-01_001"]
    other = client.get("/sources/channels/notes/items", params={"q": "reading"},
                       headers={"If-None-Match": first.headers["etag"]})
    assert other.status_code == 200, "another search is another tag"
    assert client.get("/sources/channels/notes/items", params={"q": "x" * 201}).status_code == 422


def test_latest_never_names_a_day_still_ahead(bank):
    """A calendar's coming event is not an item that came in."""
    _episode(bank, "ep_2026-09-13_002", title="Far future", origin="calendar-local", source_id="calendar-local:e9",
             timestamp="2026-09-13T08:00:00+00:00", event_start="2999-01-01T09:00:00+00:00")
    bank_index.invalidate()
    page = channel_items.items(bank, "calendar-local")
    assert page["items"][0]["day"] == "2999-01-01" and page["latest"] == "2026-10-01"


@pytest.mark.parametrize("channel,origin", [("whatsapp", "whatsapp"), ("telegram-chats", "telegram-chats")])
def test_q_finds_a_live_chat_sources_chat_row(bank, monkeypatch, channel, origin):
    """#559 lists WhatsApp and Telegram one row per chat; the source page's search finds that row by its name or by a
    sitting whose words matched, and `latest` is its newest sitting's day."""
    from api.services import search_index

    chat = "b" * 32
    for n, day in ((1, "2026-09-16"), (2, "2026-09-17")):
        _episode(bank, f"ep_{day}_00{n}", title=f"Chat · {day}", origin=origin, conversation=chat,
                 correspondent={"name": "Person C"}, message_count=3, timestamp=f"{day}T08:00:00+00:00")
    bank_index.invalidate()
    page = channel_items.items(bank, channel)
    assert [(r["kind"], r["id"], r["sittings"], r.get("messages")) for r in page["items"]] == [("chat", chat, 2, 6)]
    assert page["latest"] == "2026-09-17"
    assert channel_items.items(bank, channel, q="person c")["total"] == 1
    monkeypatch.setattr(search_index, "episodes_with_words", lambda memory_path, q: {"ep_2026-09-16_001"})
    assert [r["id"] for r in channel_items.items(bank, channel, q="climbing")["items"]] == [chat]
