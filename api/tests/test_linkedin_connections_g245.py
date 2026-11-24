"""G245 (ruling 78 (c), owner 2026-11-24): LinkedIn connections by date, and LinkedIn matching the person everywhere.

"who i have connected with and in chronological order which to me is super important" — the person's own agent reads
the connections page into the directory outside every bank (`linkedin_people.record_read`); the app lists it; the
person's agents read a date range of it. And, later the same day: "a linkedin connection doesnt need a page just for the
sake of having a page, the person is what gets a page" — a connection alone never makes a page, and the one that matches a
person being born attaches in the write that births them (`linkedin_people.Attacher`), never on a doubted name. Asked
whether one full-name mention of a connection with no Contacts card is enough: "yes it should be enough" — the person's
own words naming exactly one waiting connection make the page, its link only proposed (`test_connection_mention_page`).

Synthetic people, placeholder links; nothing reads a real bank, `~/.cicada` or the network."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import porcelain, reading  # noqa: F401 — `reading` is a fixture
from _synthetic_bank import _bank, _entity
from api import config, main
from api.remote import catalog
from api.services import (agentic_write, bank_index, conflict_resolver, contacts_local, demo_guard, entity_resolver as er,
                          fact_sources, linkedin_people, markdown_parser, people_directory, reading_settings,
                          replica_routes, same_name_doubts, saved_lists)
from api.services.claims import parse_claims

TODAY = "2026-11-24"
LI = "https://www.linkedin.com/in"


def _on():
    reading_settings.update(saved_lists_={"linkedin-connections": True})


def _record(server, items, outcome="read", **kw):
    return server.handle_tool("cicada_record_saved_list", {"platform": "linkedin-connections", "outcome": outcome,
                                                           **({"items": items} if items is not None else {}), **kw})


def _held(memory):
    return linkedin_people.load_directory(memory.name)


def _row(name, slug, connected, headline=""):
    return {"name": name, "profile_url": f"{LI}/{slug}", "headline": headline, "connected": connected}


def _li(memory, eid, predicate=None):
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)
    return [c for c in claims if c.observer == linkedin_people.OBSERVER and (predicate is None or c.predicate == predicate)]


def _sources(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter.get("sources") or []


def _kept(memory, rows, day="2026-11-01", **export):
    """A directory as an earlier read or export left it."""
    conns = [linkedin_people.Connection(r[0], r[1], f"{LI}/{r[2]}", *r[3:6]) for r in rows]
    linkedin_people.save_directory(memory.name, conns, day)


# --- reading a date off the page ------------------------------------------------------------------------------------


@pytest.mark.parametrize("said, want", [
    ("2021-03-04", ("2021-03-04", "day")), ("Connected on March 4, 2021", ("2021-03-04", "day")),
    ("04 Mar 2021", ("2021-03-04", "day")), ("Connected today", (TODAY, "day")),
    ("yesterday", ("2026-11-23", "day")), ("5 hours ago", (TODAY, "day")), ("14 days ago", ("2026-11-10", "day")),
    ("Connected 3 weeks ago", ("2026-11-03", "week")), ("a week ago", ("2026-11-17", "week")),
    ("2 months ago", ("2026-09-25", "month")), ("1 year ago", ("2025-11-24", "month")),
    ("hace 3 semanas", (None, None)), ("", (None, None)), ("2099-01-01", (None, None)), ("1999-01-01", (None, None)),
])
def test_a_date_is_a_day_and_a_precision_counted_from_the_day_it_was_read(said, want):
    assert linkedin_people.parse_connected(said, TODAY) == want


# --- the way in: the agent's own read -------------------------------------------------------------------------------


def test_the_list_is_off_until_the_person_turns_it_on_and_records_nothing_before(reading):
    server, memory = reading
    assert "linkedin-connections" in saved_lists.PLATFORMS and saved_lists.PLATFORMS["linkedin-connections"].base == "linkedin"
    assert "linkedin-connections" not in reading_settings.DEFAULT_ON_SAVED_LISTS
    assert not saved_lists.allowed("linkedin-connections")
    out = _record(server, [_row("Erin Example", "erin-example", "2026-11-03")])
    assert "has not asked" in out and not _held(memory)


def test_a_read_keeps_each_row_with_its_day_and_precision_outside_every_bank_and_writes_the_bank_nothing(reading):
    server, memory = reading
    _on()
    out = _record(server, [_row("Erin Example", "erin-example", "Connected 3 weeks ago", "Designer at Acme"),
                           _row("Finn Sample", "finn-sample", "2026-11-20"),
                           _row("Gale Undated", "gale-undated", "hace tres semanas"),
                           {"name": "No Link", "profile_url": "https://example.com/not-a-profile", "connected": "2026-11-01"},
                           {"name": "Email Person", "profile_url": f"{LI}/email-person", "email": "x@example.org",
                            "connected": "2026-11-02"}], reached_end=True)
    assert "3 new, 0 updated" not in out and "4 new" in out, out
    assert "1 row(s) had no member profile link" in out and "never read" in out and "not something the person saved" in out
    held = _held(memory)
    rows = {r["url"].rsplit("/", 1)[1]: r for r in held["connections"]}
    assert set(rows) == {"erin-example", "finn-sample", "gale-undated", "email-person"}
    assert (rows["erin-example"]["connected_on"], rows["erin-example"]["precision"]) == (
        (date.today() - timedelta(days=21)).isoformat(), "week")
    assert (rows["finn-sample"]["connected_on"], rows["finn-sample"]["precision"]) == ("2026-11-20", "day")
    assert "connected_on" not in rows["gale-undated"]
    assert rows["erin-example"]["headline"] == "Designer at Acme" and rows["erin-example"]["src"] == "read"
    assert "@" not in json.dumps(held) and '"email"' not in json.dumps(held), "there is no email field to keep"
    assert porcelain(memory) == "" and not list((memory / "entities").glob("*erin*")), "the bank is untouched"
    assert saved_lists.last(memory, "linkedin-connections")["outcome"] == "read"


def test_a_read_merges_by_link_never_deletes_keeps_the_finer_day_and_never_moves_the_exports_day_back(reading):
    server, memory = reading
    _on()
    _kept(memory, [("Erin", "Example", "erin-example", "Acme", "Designer", "2021-03-04")], day="2026-01-15")
    export_day = _held(memory)["exported_on"]
    _record(server, [_row("Erin Example", "erin-example", "3 weeks ago", "Lead at Acme"),
                     _row("Finn Sample", "finn-sample", "2 months ago")])
    held = {r["url"].rsplit("/", 1)[1]: r for r in _held(memory)["connections"]}
    assert held["erin-example"]["connected_on"] == "2021-03-04", "the exact day an export gave is the finer one"
    assert held["erin-example"]["company"] == "Acme" and held["erin-example"]["headline"] == "Lead at Acme"
    assert held["finn-sample"]["precision"] == "month"
    # A second read that does not list Erin deletes nothing, and a finer day replaces a coarser one.
    out = _record(server, [_row("Finn Sample", "finn-sample", "2026-09-30")], continues=False)
    held = {r["url"].rsplit("/", 1)[1]: r for r in _held(memory)["connections"]}
    assert set(held) == {"erin-example", "finn-sample"}
    assert (held["finn-sample"]["connected_on"], held["finn-sample"]["precision"]) == ("2026-09-30", "day")
    assert "1 updated" in out
    # The same row again moves nothing, and an export day never moves back.
    again = _record(server, [_row("Finn Sample", "finn-sample", "2026-09-30")])
    assert "0 new, 0 updated, 1 already kept" in again
    assert _held(memory)["exported_on"] == export_day == "2026-01-15"
    assert linkedin_people.status(memory.name)["connections"] == 2


def test_the_reply_counts_who_is_already_a_page_and_who_a_same_name_doubt_held_back_never_a_name(reading):
    server, memory = reading
    _on()
    _entity(memory, "erin-example", type="person", name="Erin Example")
    _entity(memory, "finn-sample", type="person", name="Finn Sample")
    _entity(memory, "finn-sample-b", type="person", name="Finn Sample")
    _entity(memory, "gale-doubt", type="person", name="Gale Doubt")
    same_name_doubts.add_pairs(memory, [("gale-doubt", "Gale Doubt")], today=TODAY)   # a page and a held line of one name
    bank_index.invalidate()
    out = _record(server, [_row("Erin Example", "erin-example", "2026-11-03"),
                           _row("Finn Sample", "finn-sample-x", "2026-11-04"),
                           _row("Gale Doubt", "gale-doubt-x", "2026-11-05"),
                           _row("Hana Stranger", "hana-stranger", "2026-11-06")])
    assert "1 of them are people already in memory" in out and "1 name(s) were held back on a same-name doubt" in out
    assert "1 match more than one person" in out
    assert not any(name in out for name in ("Erin", "Finn", "Gale", "Hana")), "a count, never a name"
    assert not _sources(memory, "erin-example"), "a read writes nothing into the bank: the tail attaches it"


def test_an_export_after_a_read_keeps_what_only_the_read_knows(reading):
    server, memory = reading
    _on()
    _record(server, [_row("Hana New", "hana-new", "2026-11-22")])
    csv = (b"First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
           b"Erin,Example,https://www.linkedin.com/in/erin-example,,Acme,Designer,04 Mar 2021\n")
    linkedin_people.import_connections(memory, csv, "Connections.csv", exported_on="2026-11-01", bank=memory.name)
    slugs = {r["url"].rsplit("/", 1)[1] for r in _held(memory)["connections"]}
    assert slugs == {"erin-example", "hana-new"}


def test_the_row_with_no_profile_link_or_name_is_left_out_and_a_page_of_nothing_is_a_failed_read(reading):
    server, memory = reading
    _on()
    out = _record(server, [{"name": "Nobody", "connected": "2026-11-01"}])
    assert "read failed" in out and not _held(memory)
    assert saved_lists.last(memory, "linkedin-connections")["outcome"] == "failed"


def test_the_queue_offers_the_connections_page_when_due_and_names_the_rails(reading):
    server, memory = reading
    _on()
    out = server.handle_tool("cicada_reading_queue", {})
    assert "mynetwork/invite-connect/connections" in out and "Recently added" in out
    assert "never a profile" in out and "contact info" in out
    assert 'platform="linkedin-connections"' in out


def test_the_stream_shows_the_connections_state_last_read_and_the_directorys_size(reading):
    server, memory = reading
    _on()
    _record(server, [_row("Erin Example", "erin-example", "2026-11-03"), _row("Finn Sample", "finn-sample", "2026-11-20")])
    config.get_settings.cache_clear()
    body = TestClient(main.app).get("/sources/streams").json()
    streams = {t["id"]: t for s in body["sources"] for t in s["streams"]}
    stream = streams["linkedin.connections"]
    assert (stream["kind"], stream["how"], stream["state"], stream["count"]) == ("connections", "browser", "on", 2)
    assert stream["lastReadAt"] and stream["switch"] == {"setting": "savedLists", "key": "linkedin-connections"}
    assert stream["health"] == "read" and stream["depth"] == "index"
    assert "linkedin.saved" in streams


# --- the list the app draws -----------------------------------------------------------------------------------------


@pytest.fixture
def listing(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "erin-example", type="person", name="Erin Example")
    _entity(memory, "pat-owner", type="person", name="Pat Owner", owner=True)
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "fixtures"], check=True, capture_output=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    linkedin_people.record_read(memory.name, [
        _row("Erin Example", "erin-example", "2026-11-03", "Designer at Acme"),
        _row("Finn Sample", "finn-sample", "2026-11-20", "Founder"),
        _row("Gale Twin", "gale-twin-1", "2026-11-20"),
        _row("Gale Twin", "gale-twin-2", "2026-10-01"),
        _row("Pat Owner", "pat-owner", "2026-09-01"),
        _row("Old Friend", "old-friend", "2019-06-01"),
        {"name": "Hana Undated", "profile_url": f"{LI}/hana-undated"}], TODAY)
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def test_the_list_is_newest_first_with_the_one_matching_page_and_filters_and_pages(listing):
    c, memory = listing
    body = c.get("/sources/linkedin-connections/list").json()
    names = [r["name"] for r in body["rows"]]
    assert names[:2] == ["Finn Sample", "Gale Twin"] and names[-1] == "Hana Undated", names
    assert [r["day"] for r in body["rows"] if r["day"]] == sorted((r["day"] for r in body["rows"] if r["day"]), reverse=True)
    rows = {r["url"].rsplit("/", 1)[1]: r for r in body["rows"]}
    assert rows["erin-example"]["page"] == "erin-example" and rows["erin-example"]["headline"] == "Designer at Acme"
    assert rows["finn-sample"]["page"] is None and rows["finn-sample"]["precision"] == "day"
    assert rows["pat-owner"]["page"] is None, "the owner's page is never anyone's connection"
    assert rows["hana-undated"]["day"] is None
    assert body["total"] == body["kept"] == 7
    assert [r["name"] for r in c.get("/sources/linkedin-connections/list", params={"query": "finn"}).json()["rows"]] == [
        "Finn Sample"]
    assert [r["name"] for r in c.get("/sources/linkedin-connections/list", params={"query": "designer acme"}).json()["rows"]] == [
        "Erin Example"]
    ranged = c.get("/sources/linkedin-connections/list", params={"since": "2026-10-01", "until": "2026-11-10"}).json()
    assert sorted(r["name"] for r in ranged["rows"]) == ["Erin Example", "Gale Twin"] and ranged["total"] == 2
    first = c.get("/sources/linkedin-connections/list", params={"limit": 3}).json()
    second = c.get("/sources/linkedin-connections/list", params={"limit": 3, "offset": first["next"]}).json()
    assert first["next"] == 3 and len(second["rows"]) == 3 and not {r["id"] for r in first["rows"]} & {
        r["id"] for r in second["rows"]}


def test_two_connections_of_one_name_match_no_page_and_the_list_has_an_etag(listing):
    c, memory = listing
    _entity(memory, "gale-twin", type="person", name="Gale Twin")
    bank_index.invalidate()
    rows = c.get("/sources/linkedin-connections/list", params={"query": "gale"}).json()["rows"]
    assert len(rows) == 2 and all(r["page"] is None for r in rows)
    response = c.get("/sources/linkedin-connections/list")
    etag = response.headers["etag"]
    assert c.get("/sources/linkedin-connections/list", headers={"If-None-Match": etag}).status_code == 304


def test_the_list_is_409_on_a_demo_bank_and_local_only(listing):
    c, memory = listing
    demo_guard.write_manifest(memory)
    assert c.get("/sources/linkedin-connections/list").status_code == 409
    assert "GET /sources/linkedin-connections/list" not in replica_routes.GET_FROM_HOME
    from api.remote import agent_api

    assert not [p for p in agent_api.openapi("https://cicada.example.ts.net")["paths"] if "connection" in p.lower()]


def test_forgetting_and_trashing_the_bank_wipe_the_list(listing):
    c, memory = listing
    assert c.delete("/sources/linkedin-connections").json()["forgotten"] == 7
    assert c.get("/sources/linkedin-connections/list").json()["rows"] == []
    linkedin_people.record_read(memory.name, [_row("Erin Example", "erin-example", "2026-11-03")], TODAY)
    people_directory.forget(memory.name)
    assert not people_directory.folder(memory.name).exists()
    assert c.get("/sources/linkedin-connections/list").json()["kept"] == 0


# --- the agents' door -----------------------------------------------------------------------------------------------


def test_the_agents_read_names_a_range_with_pages_and_is_never_remote(listing):
    c, memory = listing
    from _stdio_server import stdio_server

    server = stdio_server()
    out = server.handle_tool("cicada_linkedin_connections", {"since": "2026-10-15", "until": "2026-11-24"})
    assert "Finn Sample" in out and "Erin Example" in out and "page `erin-example`" in out
    assert "Old Friend" not in out and "Gale Twin" in out
    assert out.index("Finn Sample") < out.index("Erin Example"), "newest first"
    assert "cicada_linkedin_connections" in catalog.NEVER_REMOTE
    assert "cicada_linkedin_connections" not in catalog.READ_TOOLS and "cicada_linkedin_connections" not in catalog.WRITE_TOOLS
    assert "Invalid arguments" in server.call_tool("cicada_linkedin_connections", {"since": "last week"})["content"][0]["text"]
    fenced = server.call_tool("cicada_linkedin_connections", {"since": "2026-10-15"})["content"][0]["text"]
    assert fenced.startswith("Reference data from Cicada") and "<<<cicada-reference" in fenced


def test_at_most_fifty_rows_and_names_reach_no_bank_log_or_ledger(listing, tmp_path):
    c, memory = listing
    from _stdio_server import stdio_server

    linkedin_people.record_read(memory.name, [_row(f"Person{i} Example", f"person-{i}", "2026-11-01") for i in range(70)],
                                TODAY)
    server = stdio_server()
    for args in ({"since": "2026-10-01", "limit": 50}, {"since": "2026-10-01"}, {"since": "2026-10-01", "limit": 5}):
        out = server.handle_tool("cicada_linkedin_connections", args)
        assert len([line for line in out.splitlines() if line.startswith("- ")]) == args.get("limit", 50)
    assert "more in range" in out
    found = subprocess.run(["grep", "-rlE", "Person[0-9]+ Example|Finn Sample|Erin Example", str(memory),
                            "--exclude-dir=.git", "--exclude-dir=entities"], capture_output=True, text=True).stdout
    assert found == "", "no name is written into the bank by a read"
    home = tmp_path / "home"
    leaked = subprocess.run(["grep", "-rlE", "Person[0-9]+ Example|Finn Sample", str(home)], capture_output=True,
                            text=True).stdout.split()
    assert [p for p in leaked if not p.endswith("linkedin-connections.json")] == [], "only the directory holds a name"


def test_a_demo_bank_and_an_empty_directory_say_so(listing):
    c, memory = listing
    from _stdio_server import stdio_server

    c.delete("/sources/linkedin-connections")
    assert "No LinkedIn connections are kept" in stdio_server().handle_tool("cicada_linkedin_connections", {})
    demo_guard.write_manifest(memory)
    assert demo_guard.AGENT_REFUSAL in stdio_server().handle_tool("cicada_linkedin_connections", {})


# --- the person gets the page, never the connection ----------------------------------------------------------------


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=1)


@pytest.fixture
def stage2(tmp_path, monkeypatch):
    bank = tmp_path / "birthbank"
    for name in ("entities", "episodes", "inbox"):
        (bank / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def different(*_a, **_k):
        return "different"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["different" for _ in entries]

    monkeypatch.setattr(er, "_llm_judge_same_entity", different)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    for n in (1, 2):
        markdown_parser.write(bank / "episodes" / f"ep_2026-10-01_00{n}.md",
                              {"id": f"ep_2026-10-01_00{n}", "timestamp": "2026-10-01T12:00:00+00:00",
                               "processed": False, "harness": "claude-code"},
                              "user: lunch with Erin Example today\n\nassistant: noted")
    bank_index.invalidate()
    linkedin_people.record_read(bank.name, [_row("Erin Example", "erin-example", "2026-11-03", "Designer at Acme"),
                                            _row("Finn Sample", "finn-sample", "2026-10-05")], TODAY)
    yield bank
    bank_index.invalidate()


def _mention(name, episodes=("ep_2026-10-01_001",), named=True):
    return [{"episode_id": ep, "relationships": [], "entities": [
        {"name": name, "type": "person", "confidence": 0.6, "description": f"{name} came up.", "source_episode": ep,
         "source_episode_timestamp": "2026-10-01T12:00:00Z", "named_by_person": named}]} for ep in episodes]


def _resolve(bank, extracted, pages=()):
    return asyncio.run(er.resolve(extracted, list(pages), _settings(bank)))


def _born(bank, out):
    conflict_resolver.apply_changes(out["changes"], bank)
    bank_index.invalidate()


def test_a_connection_makes_a_page_only_when_the_person_names_it_in_full_in_their_own_words(stage2):
    """Ruling 78 (c), amended the same day (owner 2026-11-24, "yes it should be enough"): the mention makes the page and the
    connection attaches; a connection nobody mentioned still makes nothing. The rule's refusals: `test_connection_mention_page`."""
    one = _resolve(stage2, _mention("Finn Sample"))     # Stage 1 named it, but no turn of the person's holds the name
    assert not [c for c in one["changes"] if c.get("action") == "create"]
    assert not list((stage2 / "entities").glob("*"))
    in_bank = subprocess.run(["grep", "-rl", "-e", "finn-sample", "-e", "Connected with", str(stage2)],
                             capture_output=True, text=True).stdout
    assert in_bank == "", "nothing about a name's connection is written into the bank before its page exists"
    out = _resolve(stage2, _mention("Erin Example"))    # ep 001: "user: lunch with Erin Example today", once
    (change,) = [c for c in out["changes"] if c.get("action") == "create"]
    assert change["id"] == "erin-example"
    _born(stage2, out)
    (link,) = [s for s in _sources(stage2, "erin-example") if s.get("predicate") == "linkedin"]
    assert (link["ref"], link["match"], link["proposed"]) == (f"{LI}/erin-example", "alias", True), "only proposed"
    assert [c.object for c in _li(stage2, "erin-example", "connected-on")] == ["2026-11-03"]
    assert not (stage2 / "entities" / "finn-sample.md").exists(), "a connection nobody mentioned makes nothing"


def test_a_held_name_carries_its_connection_to_the_page_born_when_a_second_conversation_promotes_it(stage2, monkeypatch):
    from api.services import pending_store

    class Held:   # the pending store as Stage 2 reads it (`SqliteVecIndexer.pending_by_name`)
        def pending_by_name(self, name):
            return pending_store.held_line(stage2, name)

        def index_pending_entity(self, *a, **k):
            return None

        def rebuild_pending_index(self, *a, **k):
            return None

    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: Held())
    # One conversation named the person: the name waits in the pending store, as ever, with nothing of the connection.
    pending_store.upsert(stage2, pending_store.PendingEntity(
        name="Finn Sample", type="person", description="Finn came up.", source_episode="ep_2026-10-01_001",
        confidence=0.6, tags=[], history_entries=[], aliases=[]))
    held_text = (stage2 / pending_store.PENDING_STORE_FILE).read_text()
    assert "Finn Sample" in held_text
    assert not any(word in held_text for word in ("finn-sample", "Connected", "2026-10-05", "linkedin"))
    assert not list((stage2 / "entities").glob("*")), "a held name, a kept connection: still no page"
    out = _resolve(stage2, _mention("Finn Sample", ("ep_2026-10-01_002",)))          # the second conversation
    (change,) = [c for c in out["changes"] if c.get("action") == "create"]
    assert change["id"] == "finn-sample"
    _born(stage2, out)
    assert [s["ref"] for s in _sources(stage2, "finn-sample") if s.get("predicate") == "linkedin"] == [f"{LI}/finn-sample"]
    assert [c.object for c in _li(stage2, "finn-sample", "connected-on")] == ["2026-10-05"]


def test_a_page_born_by_the_usual_rules_gets_its_connection_in_the_same_write(stage2):
    out = _resolve(stage2, _mention("Erin Example", ("ep_2026-10-01_001", "ep_2026-10-01_002")))   # 2+ conversations
    (change,) = [c for c in out["changes"] if c.get("action") == "create"]
    assert change["id"] == "erin-example"
    _born(stage2, out)                                   # Stage 5 only: no tail, no commit
    (link,) = [s for s in _sources(stage2, "erin-example") if s.get("predicate") == "linkedin"]
    assert (link["ref"], link["added_by"], link["kind"], link["match"]) == (f"{LI}/erin-example", "cicada", "url", "name")
    assert [c.object for c in _li(stage2, "erin-example", "connected-on")] == ["2026-11-03"]
    assert _li(stage2, "erin-example", "connected-on")[0].observer == "external:linkedin"
    assert linkedin_people.rematch(stage2).paths == [], "nothing left for the night's tail"


def test_one_lead_across_a_waiting_card_and_a_waiting_connection_the_page_is_born_with_both(stage2):
    contacts_local.save_waiting(stage2.name, [{"id": "C1", "given_name": "Erin", "family_name": "Example",
                                               "has_organization": True}])
    bank_index.invalidate()
    out = _resolve(stage2, _mention("Example Erin"))      # the card's rule: one conversation, in full, the person's words
    (change,) = [c for c in out["changes"] if c.get("action") == "create"]
    assert change["contacts_card"]["id"] == "C1"
    _born(stage2, out)
    refs = {(s["predicate"], s["ref"]) for s in _sources(stage2, "erin-example")}
    assert ("works-at", "addressbook://C1") in refs and ("linkedin", f"{LI}/erin-example") in refs
    assert _li(stage2, "erin-example", "connected-on")


def test_an_agents_first_claim_about_a_new_person_births_the_page_with_the_connection(stage2):
    agentic_write.write_claim(stage2, "Finn Sample", "works-with", "Acme Robotics", observer="agent", confidence=0.6)
    assert [s["ref"] for s in _sources(stage2, "finn-sample") if s.get("predicate") == "linkedin"] == [
        f"{LI}/finn-sample"]
    assert [c.object for c in _li(stage2, "finn-sample", "connected-on")] == ["2026-10-05"]
    agentic_write.write_claim(stage2, "Zed Nobody", "works-with", "Acme Robotics", observer="agent", confidence=0.6)
    assert not _sources(stage2, "zed-nobody"), "no connection, nothing attached"


def _tool_write(bank, subject, *, connector_id):
    from api.services import mcp_tools

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_follow", harness="claude-code",
                                connector_id=connector_id, client_name="claude-code" if connector_id is None else None)
    return mcp_tools.write_claim(ctx, subject, "works-with", "Acme Robotics", "agent", 0.6, None, None)


def test_a_remote_callers_first_claim_never_attaches_a_connection_but_the_tail_still_does_and_a_local_door_attaches(stage2):
    """A remote caller must not learn, from a page's making, that a guessed name is one of the person's connections."""
    out = _tool_write(stage2, "Finn Sample", connector_id="conn_x")
    assert "NOT written" not in str(out) and "Could not" not in str(out)
    assert (stage2 / "entities" / "finn-sample.md").exists()
    assert not _sources(stage2, "finn-sample") and not _li(stage2, "finn-sample"), "remote: nothing attached at birth"
    # the night's tail attaches it
    assert linkedin_people.rematch(stage2).matched >= 1
    assert [s["ref"] for s in _sources(stage2, "finn-sample") if s.get("predicate") == "linkedin"] == [f"{LI}/finn-sample"]
    # the local door (stdio / CLI / a device token) attaches at once
    out = _tool_write(stage2, "Erin Example", connector_id=None)
    assert "Could not" not in str(out)
    assert [s["ref"] for s in _sources(stage2, "erin-example") if s.get("predicate") == "linkedin"] == [f"{LI}/erin-example"]


def _csv(*rows):
    head = "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    return (head + "".join(",".join(r) + "\n" for r in rows)).encode()


def test_rows_with_no_profile_link_and_one_name_stay_two_connections_across_a_reimport_and_the_refusal_holds(stage2):
    csv = _csv(("Gale", "Twin", "", "", "Acme", "Designer", "03 Nov 2026"),
               ("Gale", "Twin", "", "", "Beta", "Founder", "05 Nov 2026"))
    for _ in range(2):   # a re-import of the same export changes nothing
        linkedin_people.save_directory(stage2.name, linkedin_people.parse(csv).connections, "2026-11-10")
        held = _held(stage2)["connections"]
        gales = [c for c in held if c["first"] == "Gale"]
        assert len(gales) == 2 and len({c["id"] for c in gales}) == 2, "two same-name rows with no link stay two"
    _entity(stage2, "gale-twin", type="person", name="Gale Twin")
    bank_index.invalidate()
    a = _attacher(stage2)
    fm, _ = a.attach(_born_fm("Gale Twin"), "## Summary\nGale.\n", "gale-twin-new")
    assert "sources" not in fm and a.report.matched == 0, "two connections of one name: neither is theirs"
    assert linkedin_people.rematch(stage2).matched == 0 and not _sources(stage2, "gale-twin")


def test_an_export_row_with_no_link_and_a_read_of_one_person_with_one_are_one_connection_only_when_it_can_be_told(stage2):
    # Told safely: the one name in the directory, the same day to the day, the read is the agent's.
    linkedin_people.record_read(stage2.name, [_row("Hana Sample", "hana-sample", "2026-11-03")], TODAY)
    linkedin_people.save_directory(stage2.name, linkedin_people.parse(
        _csv(("Hana", "Sample", "", "", "Acme", "Designer", "03 Nov 2026"))).connections, "2026-11-10")
    held = [c for c in _held(stage2)["connections"] if c["first"] == "Hana"]
    assert len(held) == 1 and held[0]["url"] == f"{LI}/hana-sample" and held[0]["company"] == "Acme"
    # Not safe: another day, or a second row of the name — kept apart.
    linkedin_people.save_directory(stage2.name, linkedin_people.parse(
        _csv(("Hana", "Sample", "", "", "Acme", "Designer", "04 Nov 2026"))).connections, "2026-11-11")
    assert len([c for c in _held(stage2)["connections"] if c["first"] == "Hana"]) == 2
    linkedin_people.record_read(stage2.name, [_row("Ivo Sample", "ivo-sample", "2026-11-03"),
                                              _row("Ivo Sample", "ivo-sample-2", "2026-11-03")], TODAY)
    linkedin_people.save_directory(stage2.name, linkedin_people.parse(
        _csv(("Ivo", "Sample", "", "", "", "", "03 Nov 2026"))).connections, "2026-11-12")
    assert len([c for c in _held(stage2)["connections"] if c["first"] == "Ivo"]) == 3


def test_a_read_after_an_export_row_with_no_link_joins_them_under_the_same_rule(stage2):
    linkedin_people.save_directory(stage2.name, linkedin_people.parse(
        _csv(("Jun", "Sample", "", "", "Acme", "Designer", "03 Nov 2026"))).connections, "2026-11-10")
    linkedin_people.record_read(stage2.name, [_row("Jun Sample", "jun-sample", "2026-11-03")], TODAY)
    held = [c for c in _held(stage2)["connections"] if c["first"] == "Jun"]
    assert len(held) == 1 and held[0]["url"] == f"{LI}/jun-sample" and held[0]["position"] == "Designer"


def test_a_reimport_moves_imported_at_and_a_read_does_not(stage2, monkeypatch):
    from datetime import datetime as real_datetime

    stamps = iter(["2026-11-10T09:00:00+00:00", "2026-11-11T09:00:00+00:00", "2026-11-12T09:00:00+00:00"])

    class Clock(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.fromisoformat(next(stamps))

    monkeypatch.setattr(linkedin_people, "datetime", Clock)
    csv = _csv(("Kit", "Sample", f"{LI}/kit-sample", "", "", "", "03 Nov 2026"))
    linkedin_people.save_directory(stage2.name, linkedin_people.parse(csv).connections, "2026-11-10")
    first = linkedin_people.status(stage2.name)["imported_at"]
    linkedin_people.save_directory(stage2.name, linkedin_people.parse(csv).connections, "2026-11-11")
    second = linkedin_people.status(stage2.name)["imported_at"]
    assert first and second and second > first, "a re-import is a newer import"
    linkedin_people.record_read(stage2.name, [_row("Lee Sample", "lee-sample", "2026-11-03")], TODAY)
    assert linkedin_people.status(stage2.name)["imported_at"] == second, "a read is not an import"


# --- never the wrong person ----------------------------------------------------------------------------------------


def _attacher(bank):
    return linkedin_people.Attacher(bank)


def _born_fm(name, **extra):
    return {"name": name, "type": "person", "status": "active", **extra}


def test_a_same_name_doubt_refuses_a_name_only_match_at_birth_and_in_the_tail_and_counts_it(stage2):
    _entity(stage2, "erin-example-a", type="person", name="Erin Example")
    same_name_doubts.add_pairs(stage2, [("erin-example-a", "erin-example")], today=TODAY)
    bank_index.invalidate()
    a = _attacher(stage2)
    fm, body = a.attach(_born_fm("Erin Example"), "## Summary\nErin.\n", "erin-example")
    assert "sources" not in fm and "linkedin" not in body.lower()
    assert a.report.doubted == 1 and a.report.matched == 0
    # The existing page of that name is refused by the tail too (the name, not the page, is in doubt).
    report = linkedin_people.rematch(stage2)
    assert report.doubted >= 1 and not _sources(stage2, "erin-example-a")
    # A link the page itself lists still vouches: the doubt is about names.
    _entity(stage2, "erin-example-b", type="person", name="Erin Example",
            sources=[{"ref": f"{LI}/erin-example", "kind": "url", "predicate": "linkedin", "added_by": "user"}])
    bank_index.invalidate()
    assert linkedin_people.rematch(stage2).matched == 1


def test_two_pages_or_two_connections_of_one_name_refuse_and_a_different_profile_is_someone_else(stage2):
    _entity(stage2, "erin-example-old", type="person", name="Erin Example")
    bank_index.invalidate()
    a = _attacher(stage2)
    fm, _ = a.attach(_born_fm("Erin Example"), "## Summary\nErin.\n", "erin-example")
    assert "sources" not in fm and a.report.ambiguous >= 1 and a.report.matched == 0

    linkedin_people.record_read(stage2.name, [_row("Finn Sample", "finn-sample-2", "2026-10-06")], TODAY)
    fm, _ = _attacher(stage2).attach(_born_fm("Finn Sample"), "## Summary\nFinn.\n", "finn-sample")
    assert "sources" not in fm, "two connections of one name: neither is theirs"

    fm, _ = _attacher(stage2).attach(
        _born_fm("Finn Sample", sources=[{"ref": f"{LI}/someone-else", "kind": "url", "predicate": "linkedin",
                                          "added_by": "user"}]), "## Summary\nFinn.\n", "finn-sample")
    assert all(s["ref"] != f"{LI}/finn-sample" for s in fm["sources"]), "the page names another profile"


def test_a_link_the_person_removed_stays_removed_at_birth(stage2):
    a = _attacher(stage2)
    removed = [{"ref": f"{LI}/erin-example", "predicate": "linkedin", "removed_at": TODAY}]
    fm, body = a.attach(_born_fm("Erin Example", **{fact_sources.REMOVED_KEY: removed}), "## Summary\nErin.\n",
                        "erin-example")
    assert not [s for s in fm.get("sources") or [] if s.get("predicate") == "linkedin"]
    assert a.report.removed_kept_out == 1 and "Connected with" not in body


def test_the_owner_and_a_demo_bank_and_no_directory_attach_nothing(stage2):
    fm, _ = _attacher(stage2).attach(_born_fm("Erin Example", owner=True), "## Summary\nPat.\n", "erin-example")
    assert "sources" not in fm
    demo_guard.write_manifest(stage2)
    fm, _ = _attacher(stage2).attach(_born_fm("Erin Example"), "## Summary\nErin.\n", "erin-example")
    assert "sources" not in fm
    linkedin_people.forget_directory(stage2.name)
    fm, _ = _attacher(stage2).attach(_born_fm("Erin Example"), "## Summary\nErin.\n", "erin-example")
    assert "sources" not in fm


# --- the command line ------------------------------------------------------------------------------------------------


def test_the_command_line_reads_the_same_range_from_the_same_directory(tmp_path):
    from _cli import cli_env, envelope, run_cli

    memory = _bank(tmp_path, git=False)
    _entity(memory, "erin-example", type="person", name="Erin Example")
    env = cli_env(tmp_path, memory)
    work = tmp_path / "w"
    work.mkdir()
    import os

    os.environ["CICADA_HOME"] = env["CICADA_HOME"]
    try:
        linkedin_people.record_read(memory.name, [_row("Erin Example", "erin-example", "2026-11-03", "Designer"),
                                                  _row("Old Friend", "old-friend", "2019-06-01")], TODAY)
    finally:
        os.environ.pop("CICADA_HOME", None)
    out = envelope(run_cli(["linkedin", "connections", "--since", "2026-10-01", "--json"], env, cwd=work))
    text = json.dumps(out)
    assert out["ok"] is not False and "Erin Example" in text and "page `erin-example`" in text
    assert "Old Friend" not in text
