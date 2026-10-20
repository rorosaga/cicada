"""Owner rulings 2026-10-20: Contacts as a seed, and imported-only pages that stay quiet.

1. A card that matches no page waits outside every bank (`people_directory`, beside the kept LinkedIn connections);
   the first conversation that names that person in full promotes the mention on the card alone, and the page is born
   with the card's name, photo and sources. Never a one-part name, a shared name, a relation-only person, a save's
   text, or the person's own card — the "me" card belongs to the owner's page (G169).
2. A page only an import made (a saved link, video or playlist item) is quiet until the person mentions it: derived on
   every read, dimmed by the app, never asked about in the inbox.

Synthetic people and pages only.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.services import (bank_index, conflict_resolver, contacts_local, demo_guard, entity_resolver as er,
                          fact_sources, graph_builder, inbox_service, markdown_parser, mcp_tools, people_directory,
                          quiet_pages, role_people)
from api.services.claims import Claim, Evidence, write_claims

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)   # `bob-example` (person, "Bob Example")
    _entity(memory, "owner-page", type="person", name="Pat Owner", owner=True)
    subprocess.run(["git", "-C", str(memory), "add", "entities"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "fixtures"], check=True, capture_output=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _card(cid, given, family, *, org=False, email=False, phone=False, photo=None, me=False):
    body = {"id": cid, "givenName": given, "familyName": family, "hasOrganization": org, "hasEmail": email,
            "hasPhone": phone}
    if photo is not None:
        body["photoB64"] = base64.b64encode(photo).decode()
    if me:
        body["isMe"] = True
    return body


def _post(c, cards):
    r = c.post("/sources/contacts-local/sync", json={"contacts": cards})
    assert r.status_code == 200, r.text
    return r.json()


def _waiting_file(memory):
    return people_directory.path(memory.name, contacts_local.WAITING_FILE)


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


# --------------------------------------------------------------------------- 1. cards wait outside the bank


def test_an_unmatched_card_waits_outside_the_bank_with_only_what_the_app_posted(client):
    c, memory = client
    before = subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True, text=True).stdout
    body = _post(c, [_card("C1", "Erin", "Example", org=True, phone=True, photo=JPEG),
                     _card("C2", "Mononym", ""),                      # one part: can never match, never kept
                     _card("C3", "Bob", "Example", email=True)])      # matches its page, as before
    assert (body["matched"], body["unmatched"], body["waiting"]) == (1, 2, 1)
    held = json.loads(_waiting_file(memory).read_text())
    (card,) = held["cards"]
    assert set(card) == {"id", "given_name", "family_name", "has_organization", "has_phone", "photo"}
    assert (card["given_name"], card["family_name"]) == ("Erin", "Example")
    thumb = _waiting_file(memory).parent / contacts_local.WAITING_PHOTOS / card["photo"]
    assert thumb.read_bytes() == JPEG and "C1" not in card["photo"], "the file is named by a hash, never the id"
    assert _mode(_waiting_file(memory)) == 0o600 and _mode(thumb) == 0o600
    assert _mode(_waiting_file(memory).parent) == 0o700
    after = subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert before == "" and after.strip() in ("", "?? sync_state.json"), "the match commits its own page"
    in_bank = subprocess.run(["grep", "-rl", "-e", "Erin", "-e", "C1", str(memory), "--exclude-dir=.git"],
                             capture_output=True, text=True).stdout
    assert in_bank == "", "the bank gets nothing for a waiting card"
    assert not list((memory / "entities").glob("erin*")), "never a page per card"


def test_every_sync_rewrites_the_waiting_set_so_a_deleted_card_leaves_with_its_thumbnail(client):
    c, memory = client
    _post(c, [_card("C1", "Erin", "Example", photo=JPEG), _card("C4", "Finn", "Sample", photo=PNG)])
    folder = _waiting_file(memory).parent / contacts_local.WAITING_PHOTOS
    assert len(list(folder.iterdir())) == 2
    body = _post(c, [_card("C4", "Finn", "Sample", photo=PNG)])
    assert body["waiting"] == 1
    assert [r["id"] for r in contacts_local.load_waiting(memory.name)] == ["C4"]
    assert len(list(folder.iterdir())) == 1
    _post(c, [_card("C3", "Bob", "Example")])
    assert not _waiting_file(memory).exists() and list(folder.iterdir()) == []


def test_the_me_card_belongs_to_the_owners_page_never_a_namesake_and_never_waits(client):
    c, memory = client
    # The person's own card carries a name no page has: it still lands on the owner's page (G169), and does not wait.
    body = _post(c, [_card("ME", "Patricia", "Owner-Long", email=True, photo=PNG, me=True),
                     _card("C9", "Pat", "Owner", phone=True)])    # a namesake of the owner's page
    assert body["waiting"] == 0
    refs = {s["ref"] for s in fact_sources.list_sources(memory, "owner-page")}
    assert refs == {"addressbook://ME"}, "only the me card, never the namesake"
    assert markdown_parser.parse(memory / "entities" / "owner-page.md").frontmatter["contacts_photo"]["ext"] == "png"
    assert contacts_local.load_waiting(memory.name) == []


def test_a_bank_trashed_or_renamed_takes_its_waiting_cards_along(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    contacts_local.save_waiting("alpha", [{"id": "C1", "given_name": "Erin", "family_name": "Example",
                                           "photo_b64": base64.b64encode(JPEG).decode()}])
    people_directory.rename("alpha", "beta")
    assert [r["id"] for r in contacts_local.load_waiting("beta")] == ["C1"]
    assert contacts_local.load_waiting("alpha") == []
    people_directory.forget("beta")
    assert not people_directory.folder("beta").exists()


# --------------------------------------------------------------------------- 1. a first mention promotes on a card


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=1)


@pytest.fixture
def stage2(tmp_path, monkeypatch):
    bank = tmp_path / "seedbank"
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
    _episode(bank, "ep_2026-10-01_001", {"harness": "claude-code"}, "user: lunch with Erin Example today")
    _episode(bank, "ep_2026-10-01_002", {"source": "url", "media_entity_id": "media-x", "url": "https://example.com"},
             "A page that names Erin Example.")
    # Review of #391: places the name appears that are not the person saying it.
    _episode(bank, "ep_2026-10-01_003", {"source": "mcp-remote", "evidence_kind": "assistant"},
             "user: who wrote that library?\n\nassistant: Erin Example wrote that library.")    # relayed (ruling 32)
    _episode(bank, "ep_2026-10-01_004", {"harness": "claude-code"},
             "user: who touched this module last?\n\nassistant: git log says Erin Example did.")   # the agent's reply
    _episode(bank, "ep_2026-10-01_005", {"source": "tab-group", "source_id": "tab-group:chrome:Default:x"},
             "# Research\n\n- Erin Example | Profile — https://example.com/in/x")                # a tab title
    _episode(bank, "ep_2026-10-01_006", {"source": "calendar", "origin": "calendar-local"},
             "Lunch with Erin Example")                                                          # an event title
    _episode(bank, "ep_2026-10-01_007", {"source": "apple-notes"}, "Call Erin Example about the lab")  # no markers
    contacts_local.save_waiting(bank.name, [
        {"id": "C1", "given_name": "Erin", "family_name": "Example", "has_organization": True, "has_email": True,
         "photo_b64": base64.b64encode(JPEG).decode()},
        {"id": "C5", "given_name": "Gale", "family_name": "Twin"}, {"id": "C6", "given_name": "Gale", "family_name": "Twin"},
    ])
    bank_index.invalidate()
    return bank


def _episode(bank, eid, fm, body):
    markdown_parser.write(bank / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": "2026-10-01T12:00:00+00:00", "processed": False, **fm}, body)


def _mention(name, *, episode="ep_2026-10-01_001", etype="person", named=True, **extra):
    """One Stage-1 mention. ``named`` is what `promotion.measure` set; the cases below force it True where Stage 1
    would have, or might wrongly have, so the turn check is tested on its own."""
    return [{"episode_id": episode, "relationships": [], "entities": [
        {"name": name, "type": etype, "confidence": 0.6, "description": f"{name} came up.", "source_episode": episode,
         "source_episode_timestamp": "2026-10-01T12:00:00Z", "named_by_person": named, **extra}]}]


def _resolve(bank, extracted, pages=()):
    return asyncio.run(er.resolve(extracted, list(pages), _settings(bank)))


def test_one_conversation_naming_a_waiting_card_in_full_promotes_under_the_cards_name(stage2):
    out = _resolve(stage2, _mention("Example Erin"))     # family name first: the same card
    (change,) = out["changes"]
    assert (change["action"], change["id"], change["entity"]["name"]) == ("create", "erin-example", "Erin Example")
    assert "Example Erin" in change["entity"]["aliases"], "the name the conversation used is kept"
    assert change["contacts_card"]["id"] == "C1"
    assert out["name_to_id"]["example erin"] == "erin-example"


@pytest.mark.parametrize("why, extracted, pages", [
    ("a one-part name", _mention("Erin"), ()),
    ("two cards share the name", _mention("Gale Twin"), ()),
    ("a save's text is not a conversation", _mention("Erin Example", episode="ep_2026-10-01_002"), ()),
    ("not a person", _mention("Erin Example", etype="project"), ()),
    ("a relation-only person", _mention("Erin Example", **{role_people.UNNAMED_KEY: True}), ()),
    ("Stage 1 measured nobody named it", _mention("Erin Example", named=False), ()),
    ("a relayed connector turn", _mention("Erin Example", episode="ep_2026-10-01_003"), ()),
    ("only the agent's reply names it", _mention("Erin Example", episode="ep_2026-10-01_004"), ()),
    ("a tab group's tab title", _mention("Erin Example", episode="ep_2026-10-01_005"), ()),
    ("a calendar event's title", _mention("Erin Example", episode="ep_2026-10-01_006"), ()),
    ("a body with no turn markers", _mention("Erin Example", episode="ep_2026-10-01_007"), ()),
    ("a page already holds the name", _mention("Erin Example"),
     ({"id": "erin-e", "frontmatter": {"name": "Erin E", "type": "person", "aliases": ["Erin Example"]},
       "body": "## Summary\nA page."},)),
])
def test_a_card_never_promotes(stage2, why, extracted, pages):
    out = _resolve(stage2, extracted, pages)
    assert not [c for c in out["changes"] if c.get("action") == "create"], why


def test_a_demo_bank_never_reads_the_waiting_cards(stage2):
    demo_guard.write_manifest(stage2)
    out = _resolve(stage2, _mention("Erin Example"))
    assert out["changes"] == []


def test_stage5_births_the_page_with_the_cards_sources_and_photo(stage2):
    out = _resolve(stage2, _mention("Erin Example"))
    conflict_resolver.apply_changes(out["changes"], stage2)
    fm = markdown_parser.parse(stage2 / "entities" / "erin-example.md").frontmatter
    assert fm["name"] == "Erin Example"
    assert [(s["ref"], s["predicate"], s["added_by"]) for s in fm["sources"]] == [
        ("addressbook://C1", "works-at", "cicada"), ("addressbook://C1", "email", "cicada")]
    assert fm["contacts_photo"]["ext"] == "jpg"
    assert contacts_local.photo_path(stage2.name, "erin-example", "jpg").read_bytes() == JPEG


def test_the_tail_matches_a_waiting_card_to_a_page_born_later_and_it_stops_waiting(stage2):
    _entity(stage2, "erin-example", type="person", name="Erin Example")   # promoted some other way
    _entity(stage2, "gale-twin", type="person", name="Gale Twin")          # two cards: neither lands
    report = contacts_local.rematch(stage2)
    assert report.paths == ["entities/erin-example.md"]
    assert {s["ref"] for s in fact_sources.list_sources(stage2, "erin-example")} == {"addressbook://C1"}
    assert sorted(r["id"] for r in contacts_local.load_waiting(stage2.name)) == ["C5", "C6"]
    assert contacts_local.rematch(stage2).paths == [], "idempotent"


def test_the_tail_leaves_a_page_dirty_before_it_alone(stage2):
    _entity(stage2, "erin-example", type="person", name="Erin Example")
    report = contacts_local.rematch(stage2, skip=frozenset({"entities/erin-example.md"}))
    assert report.paths == [] and len(contacts_local.load_waiting(stage2.name)) == 3


# --------------------------------------------------------------------------- 2. quiet pages


def _save(memory, eid="media-saved-video", ep="ep_2026-10-02_001"):
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "timestamp": "2026-10-02T09:00:00+00:00", "source": "youtube",
                           "media_entity_id": eid, "url": "https://example.com/v", "processed": True},
                          "# Saved video")
    _entity(memory, eid, type="media", name="A Saved Video", source_episodes=[ep],
            media={"url": "https://example.com/v", "media_type": "youtube"})


def _quiet(memory, eid):
    bank_index.invalidate(memory)
    return quiet_pages.page_is_quiet(memory, eid)


def test_a_saved_page_is_quiet_until_a_conversation_names_it(tmp_path):
    memory = _bank(tmp_path, git=False)
    _save(memory)
    assert _quiet(memory, "media-saved-video")
    # A watched video and Cicada's own source check still say nothing about the person mentioning it.
    for ep, source in (("ep_2026-10-03_001", "video-watch"), ("ep_2026-10-03_002", "source-check")):
        markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "source": source}, "assistant: read it")
        page = markdown_parser.parse(memory / "entities" / "media-saved-video.md")
        page.frontmatter["source_episodes"].append(ep)
        markdown_parser.write(memory / "entities" / "media-saved-video.md", page.frontmatter, page.body)
        assert _quiet(memory, "media-saved-video"), source
    # Sleep credits the conversation that mentions it: quiet ends, with nothing written but that credit.
    page = markdown_parser.parse(memory / "entities" / "media-saved-video.md")
    page.frontmatter["source_episodes"].append("ep_2026-09-01_001")      # a conversation (`_bank`'s own)
    markdown_parser.write(memory / "entities" / "media-saved-video.md", page.frontmatter, page.body)
    assert not _quiet(memory, "media-saved-video")


def test_a_claim_in_the_persons_own_words_lights_a_saved_page(tmp_path):
    memory = _bank(tmp_path, git=False)
    _save(memory)
    page = markdown_parser.parse(memory / "entities" / "media-saved-video.md")
    claim = Claim(id="clm_x", text="liked it", subject="media-saved-video", predicate="note", object="liked",
                  observer="owner", evidence=[Evidence(episode="ep_2026-10-02_001", start=0, end=3, kind="user")])
    markdown_parser.write(memory / "entities" / "media-saved-video.md", page.frontmatter,
                          write_claims(page.body, [claim]))
    assert not _quiet(memory, "media-saved-video")


def test_pages_nobody_imported_are_never_quiet(tmp_path):
    memory = _bank(tmp_path, git=False)
    _entity(memory, "seeded", type="project")                          # no episode at all
    _entity(memory, "owner-page", type="media", owner=True, media={"url": "https://example.com"})
    _entity(memory, "talked", type="project", source_episodes=["ep_2026-09-01_001"])
    assert not any(_quiet(memory, e) for e in ("seeded", "owner-page", "talked", "missing-page"))


def test_the_graph_and_the_card_say_quiet_and_the_inbox_never_asks(client):
    c, memory = client
    _save(memory)
    markdown_parser.write(memory / "inbox" / "inbox-050.md",
                          {"kind": "decay", "status": "pending", "entity_id": "media-saved-video",
                           "entity_name": "A Saved Video", "title": "Still keeping it?", "created_date": "2026-10-02"},
                          "ctx")
    bank_index.invalidate()
    graph = c.get("/graph").json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["media-saved-video"]["quiet"] is True
    assert "quiet" not in nodes["bob-example"], "omitted when false"
    assert c.get("/entities/media-saved-video").json()["quiet"] is True
    assert c.get("/entities/bob-example").json()["quiet"] is False
    served = {i["id"] for i in c.get("/inbox").json()}
    assert "inbox-050" not in served and "inbox-001" in served
    assert inbox_service.served_counts(memory)[0] == len(served)
    assert not mcp_tools.nudge_visible({"kind": "decay", "entity_id": "media-saved-video"}, wanted=frozenset(),
                                       today="2026-10-20", memory_path=memory)
    # The first mention lights it and the question comes back — nothing was deleted.
    page = markdown_parser.parse(memory / "entities" / "media-saved-video.md")
    page.frontmatter["source_episodes"].append("ep_2026-09-01_001")
    markdown_parser.write(memory / "entities" / "media-saved-video.md", page.frontmatter, page.body)
    bank_index.invalidate()
    assert "quiet" not in {n["id"]: n for n in c.get("/graph").json()["nodes"]}["media-saved-video"]
    assert "inbox-050" in {i["id"] for i in c.get("/inbox").json()}


def test_a_quiet_node_hashes_differently_so_the_apps_delta_repaints_it(tmp_path):
    memory = _bank(tmp_path, git=False)
    _save(memory)
    bank_index.invalidate()
    before = {n.id: n.content_hash for n in graph_builder.build_graph(memory).nodes}
    page = markdown_parser.parse(memory / "entities" / "media-saved-video.md")
    page.frontmatter["source_episodes"].append("ep_2026-09-01_001")
    markdown_parser.write(memory / "entities" / "media-saved-video.md", page.frontmatter, page.body)
    bank_index.invalidate()
    after = {n.id: n.content_hash for n in graph_builder.build_graph(memory).nodes}
    assert before["media-saved-video"] != after["media-saved-video"]
    assert before["bob-example"] == after["bob-example"]


def test_the_quiet_rules_source_names_are_the_writers_own():
    from api.services import check_record, history_index, linkedin_people, source_refresh, watch_history, \
        watch_record, web_settle

    assert quiet_pages.WATCH_SOURCES == {watch_record.SOURCE, watch_history.SOURCE, history_index.MONTH_SOURCE}
    assert quiet_pages.CHECK_SOURCES == {check_record.SOURCE, source_refresh.ORIGIN, web_settle.SOURCE,
                                         linkedin_people.PROFILE_SOURCE}


# --------------------------------------------------------------------------- stopping Contacts forgets the cards


def test_disconnecting_contacts_forgets_every_banks_waiting_cards_and_nothing_uses_them_after(stage2, monkeypatch):
    from api.services import auth

    contacts_local.save_waiting("other-bank", [{"id": "C7", "given_name": "Hal", "family_name": "Sample",
                                                "photo_b64": base64.b64encode(PNG).decode()}])
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    c = TestClient(main.app)
    assert c.delete("/sources/contacts-local/waiting").status_code == 401, "token-gated like every sources route"
    r = c.delete("/sources/contacts-local/waiting", headers={"Authorization": f"Bearer {auth.get_token()}"})
    assert r.status_code == 200 and r.json() == {"forgotten": 4}
    for bank in (stage2.name, "other-bank"):
        folder = people_directory.folder(bank)
        assert not (folder / contacts_local.WAITING_FILE).exists()
        assert not (folder / contacts_local.WAITING_PHOTOS).exists()
    assert contacts_local.waiting_index(stage2).cards == {}
    assert _resolve(stage2, _mention("Erin Example"))["changes"] == [], "no first mention promotes on a forgotten card"
    _entity(stage2, "erin-example", type="person", name="Erin Example")
    assert contacts_local.rematch(stage2).paths == [], "and the tail matches nothing"
    assert fact_sources.list_sources(stage2, "erin-example") == []
    config.get_settings.cache_clear()


def test_forgetting_linkedin_connections_stops_the_rematch(tmp_path, monkeypatch):
    from api.services import linkedin_people

    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    linkedin_people.save_directory(memory.name, [linkedin_people.Connection(
        "Ivy", "Example", "https://www.linkedin.com/in/ivy-example", "Acme Example", "Engineer", "2024-01-02")],
        "2026-10-01")
    r = TestClient(main.app).delete("/sources/linkedin-connections")
    assert r.status_code == 200 and r.json()["forgotten"] == 1
    assert not linkedin_people.directory_path(memory.name).exists()
    _entity(memory, "ivy-example", type="person", name="Ivy Example")
    assert linkedin_people.rematch(memory).paths == []
    config.get_settings.cache_clear()
