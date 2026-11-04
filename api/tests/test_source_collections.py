"""2026-11-04 — where an item lives in the app it came from: accounts → collections → items on the Sources page.

Notes keep each note's account and folder in the Notes index; Calendar and Reminders keep what their last sync named
beside it (`source_collections`); `GET /sources/channels/{id}/collections` answers the tree and `collection` narrows a
channel's items. Synthetic banks only; placeholders for every name.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import channel_items, notes_sync, source_collections, sync_state

FS, RS = notes_sync.FIELD_SEP, notes_sync.RECORD_SEP
run = asyncio.run


def _note(nid, name, folder, *, account=None, modified="Monday 1", fields=9):
    parts = [nid, name, f"{name} body", "Monday", modified, folder]
    if fields >= 8:
        parts += ["2026-10-01T10:00:00", "0"]
    if fields == 9:
        parts.append(account or "")
    return FS.join(parts)


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "memory"
    (b / "episodes").mkdir(parents=True)
    return b


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(bank.parent / "home"))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _index(bank):
    return json.loads((bank / "sources" / notes_sync.NOTES_INDEX_FILENAME).read_text())


# --- Notes: the account rides a ninth field and lands in the index ------------------------------------------------


def test_a_nine_field_record_carries_its_account_and_older_records_still_parse():
    nine, eight, six = (notes_sync.parse_notes_dump(_note("n1", "A", "Work", account="iCloud", fields=n))[0]
                        for n in (9, 8, 6))
    assert (nine.account, nine.folder) == ("iCloud", "Work")
    assert eight.account == "" and eight.modified_at and six.account == "" and not six.modified_at



def test_notes_index_places_each_note_and_an_unchanged_note_is_placed_without_a_new_episode(bank, monkeypatch):
    async def _no_commit(*a, **k):
        return None

    monkeypatch.setattr(notes_sync, "_commit_notes_sync", _no_commit)
    # An older app: no accounts.
    first = run(notes_sync.sync_notes(bank, dump=RS.join([_note("n1", "Plan", "Work", fields=8),
                                                            _note("n2", "List", "Notes", fields=8)])))
    assert first["new"] == 2
    assert _index(bank)["n1"]["account"] is None and _index(bank)["n1"]["folder"] == "Work"
    episodes = sorted(p.name for p in (bank / "episodes").iterdir())
    # The new app names the accounts; nothing about the notes changed, so no episode is written — the index places them.
    again = run(notes_sync.sync_notes(bank, dump=RS.join([_note("n1", "Plan", "Work", account="iCloud"),
                                                            _note("n2", "List", "Notes", account="On My Mac")])))
    assert again == {**again, "new": 0, "updated": 0, "skipped": 2}
    assert sorted(p.name for p in (bank / "episodes").iterdir()) == episodes
    assert (_index(bank)["n1"]["account"], _index(bank)["n2"]["account"]) == ("iCloud", "On My Mac")
    # A note moved to another folder is placed there; an older app's record keeps the account already known.
    run(notes_sync.sync_notes(bank, dump=_note("n1", "Plan", "Archive", fields=8)))
    assert (_index(bank)["n1"]["account"], _index(bank)["n1"]["folder"]) == ("iCloud", "Archive")



def test_the_route_takes_each_notes_account_beside_the_dump(client, bank):
    """The app sends the account by note id beside 8-field records, so an older backend still reads every note."""
    dump = RS.join([_note("n1", "Plan", "Work", fields=8), _note("n2", "List", "Notes", fields=8)])
    r = client.post("/sources/sync-notes", json={"notesDump": dump, "noteAccounts": {"n1": "iCloud", "x": "Other"}})
    assert r.status_code == 200, r.text
    assert (_index(bank)["n1"]["account"], _index(bank)["n2"]["account"]) == ("iCloud", None)
    # Without the key (an older app), nothing is placed and nothing breaks.
    assert client.post("/sources/sync-notes", json={"notesDump": dump}).status_code == 200
    assert _index(bank)["n1"]["account"] == "iCloud"


def test_notes_collections_are_accounts_then_folders_and_a_folder_narrows_the_items(bank, monkeypatch):
    async def _no_commit(*a, **k):
        return None

    monkeypatch.setattr(notes_sync, "_commit_notes_sync", _no_commit)
    run(notes_sync.sync_notes(bank, dump=RS.join([
        _note("n1", "Plan", "Work", account="Google"),
        _note("n2", "List", "Notes", account="On My Mac"),
        _note("n3", "Books", "Personal", account="iCloud"),
        _note("n4", "Recipes", "Notes", account="iCloud"),
    ])))
    tree = channel_items.collections(bank, "notes")
    assert [a["name"] for a in tree["accounts"]] == ["iCloud", "On My Mac", "Google"]
    icloud = tree["accounts"][0]
    assert icloud["count"] == 2 and [c["name"] for c in icloud["collections"]] == ["Notes", "Personal"]
    personal = icloud["collections"][1]
    page = channel_items.items(bank, "notes", collection=personal["id"])
    assert [i["title"] for i in page["items"]] == ["Books"] and page["all"] == 1
    # The same account and folder name in another account is another collection.
    assert icloud["collections"][0]["id"] != tree["accounts"][1]["collections"][0]["id"]
    # Nothing private rides the rows.
    assert all(not k.startswith("_") for i in page["items"] for k in i)


# --- Calendar and Reminders: what the last sync named --------------------------------------------------------------


def _calendar_body(now):
    cals = [{"id": "c-home", "title": "Home", "account": "iCloud", "provider": "icloud"},
            {"id": "c-g", "title": "Work", "account": "bob@example.invalid", "provider": "google"},
            {"id": "c-empty", "title": "Holidays", "account": "Subscribed Calendars", "provider": "subscribed"},
            {"id": "c-x", "title": "Team", "account": "Exchange", "provider": "nonsense"}]
    events = [{"id": f"e{i}", "calendarId": cal, "title": title, "start": (now - timedelta(days=i)).isoformat()}
              for i, (cal, title) in enumerate([("c-home", "Dentist"), ("c-g", "Alpha sync"), ("c-g", "Review"),
                                                ("c-x", "Planning")])]
    return {"window": {"from": (now - timedelta(days=30)).isoformat(), "to": (now + timedelta(days=30)).isoformat()},
            "calendars": cals, "events": events}


def test_calendar_sync_keeps_its_calendars_and_the_tree_groups_them_by_account(client, bank):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = client.post("/sources/calendar-local/sync", json=_calendar_body(now))
    assert r.status_code == 200, r.text
    kept = source_collections.known(bank, "calendar-local")
    assert kept["c-g"] == {"id": "c-g", "title": "Work", "account": "bob@example.invalid", "provider": "google"}
    assert kept["c-x"]["provider"] == "other"      # a word the app never sends is filed as other
    tree = client.get("/sources/channels/calendar-local/collections")
    assert tree.status_code == 200, tree.text
    accounts = tree.json()["accounts"]
    assert accounts[0]["name"] == "iCloud" and accounts[0]["provider"] == "icloud"
    google = next(a for a in accounts if a["provider"] == "google")
    assert google["count"] == 2 and google["collections"][0]["name"] == "Work"
    # A calendar with nothing in it is still listed under its account.
    holidays = next(a for a in accounts if a["provider"] == "subscribed")["collections"][0]
    assert (holidays["name"], holidays["count"]) == ("Holidays", 0)
    page = client.get("/sources/channels/calendar-local/items", params={"collection": "c-g"}).json()
    assert sorted(i["title"] for i in page["items"]) == ["Alpha sync", "Review"]
    # The ETag answers 304, and moves when the calendars change.
    etag = tree.headers["etag"]
    assert client.get("/sources/channels/calendar-local/collections",
                      headers={"If-None-Match": etag}).status_code == 304
    body = _calendar_body(now)
    body["calendars"][0]["title"] = "House"
    client.post("/sources/calendar-local/sync", json=body)
    assert client.get("/sources/channels/calendar-local/collections",
                      headers={"If-None-Match": etag}).status_code == 200


def test_an_older_app_sends_no_provider_and_an_older_sync_named_nothing(client, bank):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    body = _calendar_body(now)
    for cal in body["calendars"]:
        cal.pop("provider")
    assert client.post("/sources/calendar-local/sync", json=body).status_code == 200
    assert source_collections.known(bank, "calendar-local")["c-home"]["provider"] is None
    # A sync from before collections were kept: the items still group, under the channel's own word.
    state = sync_state.read_sync_state(bank)
    state["calendar-local"].pop(source_collections.KEY)
    (bank / sync_state.SYNC_STATE_FILENAME).write_text(json.dumps(state))
    accounts = channel_items.collections(bank, "calendar-local")["accounts"]
    assert len(accounts) == 1 and accounts[0]["name"] is None
    assert {c["name"] for c in accounts[0]["collections"]} == {"Calendar"}


def test_reminders_lists_are_collections(client, bank):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    body = {"completedSince": (now - timedelta(days=30)).isoformat(),
            "lists": [{"id": "l1", "title": "Errands", "account": "iCloud", "provider": "icloud"},
                      {"id": "l2", "title": "Work", "account": "Exchange", "provider": "exchange"}],
            "reminders": [{"id": "r1", "listId": "l1", "title": "Buy stamps",
                           "created": (now - timedelta(days=1)).isoformat()},
                          {"id": "r2", "listId": "l2", "title": "Send notes",
                           "created": (now - timedelta(days=2)).isoformat()}]}
    assert client.post("/sources/reminders-local/sync", json=body).status_code == 200
    accounts = client.get("/sources/channels/reminders-local/collections").json()["accounts"]
    assert [(a["name"], a["provider"], a["count"]) for a in accounts] == [("iCloud", "icloud", 1),
                                                                          ("Exchange", "exchange", 1)]
    page = client.get("/sources/channels/reminders-local/items", params={"collection": "l2"}).json()
    assert [i["title"] for i in page["items"]] == ["Send notes"]


def test_a_channel_with_no_collections_answers_no_accounts_and_an_unknown_one_404s(client):
    assert client.get("/sources/channels/contacts-local/collections").json() == {"channel": "contacts-local",
                                                                                 "accounts": []}
    assert client.get("/sources/channels/nope/collections").status_code == 404


def test_a_meeting_row_says_how_long_it_ran(bank):
    def episode(ep_id, **fm):
        lines = ["---"] + [f"{k}: {json.dumps(v)}" for k, v in {"id": ep_id, "processed": False, **fm}.items()]
        (bank / "episodes" / f"{ep_id}.md").write_text("\n".join(lines + ["---", "", "words"]), encoding="utf-8")

    episode("ep_2026-11-03_001", title="Alpha planning", origin="folder", folder_id="f1", folder_kind="meetings",
            relpath="2026-11-03 1601 Alpha planning.md", timestamp="2026-11-03T16:01:00+00:00",
            meeting={"recorder": "hex", "duration_s": 750})
    episode("ep_2026-11-02_001", title="No length", origin="folder", folder_id="f1", folder_kind="meetings",
            relpath="b.md", timestamp="2026-11-02T09:00:00+00:00", meeting={"recorder": "hex"})
    episode("ep_2026-11-01_001", title="A note", origin="folder", folder_id="f2", relpath="n.md",
            timestamp="2026-11-01T09:00:00+00:00", meeting={"duration_s": 60})
    rows = {r["title"]: r for r in channel_items._folder(bank, "f1")}
    assert rows["Alpha planning"]["duration_s"] == 750 and "duration_s" not in rows["No length"]
    assert "duration_s" not in channel_items._folder(bank, "f2")[0]


def test_stored_clips_and_drops_what_is_not_a_collection():
    long = "x" * 400
    out = source_collections.stored([{"id": "a", "title": long, "account": "  iCloud ", "provider": "ICLOUD"},
                                     {"title": "no id"}, "junk"])
    assert len(out) == 1 and len(out[0]["title"]) == source_collections.TITLE_CAP
    assert (out[0]["account"], out[0]["provider"]) == ("iCloud", "icloud")
