"""G245 (arrival join): what the join writes, how it is recorded, and how the person takes it back — built whole and tested on
scratch banks with `LIVE` forced on IN THE TEST ONLY (it ships false, `test_arrival_join.py`).

The join IS the alias: the arrival's full name is added to the first-name page, one `cicada` commit, its own path only. The
existing rematches attach (a LinkedIn link that is never confident and asks for no photo; a Contacts card's sources and
photo), and a final step records which commits the join caused. "Not them" takes all of it back, refuses the pair for every
later joiner, and — when the person changed the name or a link since — writes nothing and says what is left. Names invented."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (arrival_join as aj, arrival_join_write as w, bank_index, contacts_local, fact_sources,
                          linkedin_people, markdown_parser, merge_rejections, page_history, people_directory, person_photo,
                          sleep_cycle)
from api.services.claims import parse_claims
from benchmarks.consolidation import arrival_join_battery as battery

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
CONNECTED = battery.d(2)


class World:
    def __init__(self, tmp_path, monkeypatch, scene: battery.Scene):
        monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(aj, "LIVE", True)           # forced on in the test only: it ships false
        self.mp = monkeypatch
        self.mem = battery.build(tmp_path, scene)
        self.judge = None
        self.set_judge("fits", "fits")

    def set_judge(self, *answers):
        seq = list(answers)

        async def judge(system, prompt):
            return {"verdict": seq.pop(0) if seq else "unsure", "quote": "", "reason": "x"}

        async def engine(settings, *, user_triggered):
            return judge, ""

        self.mp.setattr(aj, "_engine_judge", engine)

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.mem), *args], capture_output=True, text=True).stdout

    def subjects(self) -> list[str]:
        return self.git("log", "--format=%s").splitlines()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def page(self, eid="sam"):
        return markdown_parser.parse(self.mem / "entities" / f"{eid}.md")

    def night(self, *, judge=("fits", "fits")):
        """The tail's own steps, in the tail's order (`_run_engine_independent_tail`): refusals, the join, both rematches, the record."""
        self.set_judge(*judge)
        bank_index.invalidate(self.mem)

        async def go():
            await sleep_cycle._arrival_refusals_safely(self.mem)
            await sleep_cycle._arrival_join_safely(self.mem, None, user_triggered=False, no_model=False)
            await sleep_cycle._rematch_linkedin_safely(self.mem)
            await sleep_cycle._rematch_contacts_safely(self.mem)
            await sleep_cycle._arrival_record_safely(self.mem)

        asyncio.run(go())
        bank_index.invalidate(self.mem)

    def status(self) -> str:
        return self.git("status", "--porcelain")


def scene(**kw) -> battery.Scene:
    base = dict(conns=[battery.conn("Sam", "Okafor", CONNECTED, company="Alpha Robotics", position="Founder", headline="Founder")])
    base.update(kw)
    return battery.Scene(**base)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, scene())


# --- the join --------------------------------------------------------------------------------------------------------


def test_the_join_is_the_alias_one_cicada_commit_of_its_own_page_and_nothing_else(world):
    before = world.page().body
    head = world.head()
    world.night()
    subjects = world.subjects()
    assert [s.rsplit(" ", 1)[0] for s in subjects[:3]] == ["Arrival join recorded", "LinkedIn connections", "Arrival join"]
    join_sha = next(line.split()[0] for line in world.git("log", "--format=%h %s").splitlines() if " Arrival join 20" in line)
    assert world.git("show", "--name-only", "--format=", join_sha).split() == ["entities/sam.md"]
    page = world.page()
    assert page.frontmatter["name"] == "Sam" and page.frontmatter["aliases"] == ["Sam Okafor"]      # the title stays
    assert page.body.split("```")[0].strip() == before.split("```")[0].strip()                                        # prose untouched
    body = world.git("show", "--format=%B", "-s", join_sha)
    assert "Cicada-Author: cicada" in body and "trigger: sleep/arrival-join" in body and "2 days apart" in body
    assert "Okafor" not in body and "Alpha Robotics" not in body and "linkedin" not in body.lower()    # never a row's own words
    assert head != world.head()


def test_the_rematches_that_follow_attach_the_link_as_a_guess_that_asks_for_no_photo(world):
    world.night()
    source = next(s for s in fact_sources.as_sources(world.page().frontmatter["sources"]) if s["predicate"] == "linkedin")
    assert (source["added_by"], source["match"]) == ("cicada", "alias")
    assert person_photo.is_own_account(source) is False              # never confident: no photo request leaves the Mac
    assert not fact_sources.trusted(source)
    claims = {c.predicate: c for c in parse_claims(world.page().body) if c.observer == linkedin_people.OBSERVER}
    assert claims["works-at"].object == "Alpha Robotics" and claims["connected-on"].valid_from == CONNECTED
    subjects = world.subjects()
    assert any(s.startswith("LinkedIn connections") for s in subjects)


def test_the_record_names_the_commits_the_join_caused_the_claims_and_a_hash_of_each_link_never_a_name(world):
    world.night()
    record = w.latest(world.page().frontmatter, w.JOINED)
    assert record["state"] == "joined" and "pre" not in record
    assert record["days"] == {"holder": battery.d(0), "arrival": CONNECTED} and record["delta"] == 2
    assert len(record["commits"]) == 2                              # the alias commit, the LinkedIn rematch's
    assert len(record["claims"]) == 3 and all(c.startswith("clm_sam_") for c in record["claims"])
    assert len(record["sources"]) == 1 and record["sources"][0] != "https://www.linkedin.com/in/sam-okafor"
    text = json.dumps(record)
    for secret in ("Okafor", "Alpha", "Founder", "linkedin.com", "sam-okafor"):
        assert secret not in text, secret
    assert w.joined_for(world.mem)[record["refs"][0]]["page"] == "sam"


def test_a_second_night_writes_nothing_and_a_third_neither(world):
    world.night()
    head = world.head()
    world.night()
    world.night()
    assert world.head() == head and world.status() == ""


def test_a_contacts_card_of_the_name_attaches_through_its_own_rematch_with_its_photo(tmp_path, monkeypatch):
    import base64

    w2 = World(tmp_path, monkeypatch, scene(conns=[], cards=[("Sam", "Okafor", CONNECTED)]))
    contacts_local.save_waiting(w2.mem.name, [{"id": "card-0", "given_name": "Sam", "family_name": "Okafor",
                                               "has_organization": True, "has_email": True,
                                               "photo_b64": base64.b64encode(JPEG).decode()}])
    w2.night()
    assert w2.page().frontmatter["aliases"] == ["Sam Okafor"]
    refs = {(s["ref"], s["predicate"]) for s in fact_sources.as_sources(w2.page().frontmatter["sources"])}
    assert ("addressbook://card-0", "works-at") in refs and ("addressbook://card-0", "email") in refs
    assert w2.page().frontmatter["contacts_photo"]["ext"] == "jpg"
    assert any(s.startswith("Contacts") for s in w2.subjects())
    record = w.latest(w2.page().frontmatter, w.JOINED)
    assert record["contacts"] is True and len(record["sources"]) == 2 and len(record["commits"]) == 2
    assert contacts_local.waiting_status(w2.mem.name) == {"waiting": 0}


def test_a_page_with_an_uncommitted_edit_is_left_alone_tonight(world):
    path = world.mem / "entities" / "sam.md"
    path.write_text(path.read_text() + "\nan edit the person has not committed\n")
    world.night()
    assert "aliases" not in world.page().frontmatter
    assert not any(s.startswith("Arrival join 20") for s in world.subjects())


def test_apply_join_refuses_when_the_page_changed_since_the_decision(world):
    decision = _decision(world)
    fm = world.page().frontmatter
    markdown_parser.write(world.mem / "entities" / "sam.md", {**fm, "status": "archived"}, world.page().body)
    assert w.apply_join(world.mem, decision) is None
    markdown_parser.write(world.mem / "entities" / "sam.md", {**fm, "aliases": ["Sam Berg"]}, world.page().body)
    assert w.apply_join(world.mem, decision) is None
    markdown_parser.write(world.mem / "entities" / "sam.md", fm, world.page().body)
    assert w.apply_join(world.mem, decision, skip=frozenset({"entities/sam.md"})) is None
    assert w.apply_join(world.mem, decision) is not None


def test_apply_join_refuses_a_name_that_left_the_directory_or_whose_hash_differs(world):
    decision = _decision(world)
    assert w.apply_join(world.mem, aj.Decision(**{**decision.__dict__, "alias_key": "0" * 16})) is None
    linkedin_people.forget_directory(world.mem.name)
    assert w.apply_join(world.mem, decision) is None


def test_a_page_of_that_name_born_since_is_never_joined_by_alias(world):
    decision = _decision(world)
    (world.mem / "entities" / "sam-okafor.md").write_text("---\nname: Sam Okafor\ntype: person\n---\n")
    assert w.apply_join(world.mem, decision) is None


def _decision(world):
    bank_index.invalidate(world.mem)
    case = aj.gather(world.mem).cases[0]
    return aj.decide(case, aj.Veto(("fits", "fits")))


# --- "Not them" ------------------------------------------------------------------------------------------------------


def test_not_them_takes_the_name_the_link_and_the_facts_back_and_remembers_the_pair(world):
    world.night()
    out = w.undo(world.mem, "sam", before=None)
    page = world.page()
    fm = page.frontmatter
    assert "aliases" not in fm and fm["name"] == "Sam"
    assert [r["alias"] for r in fm["aliases_removed"]] == ["Sam Okafor"] and fm["aliases_removed"][0]["by"] == "user"
    assert not [s for s in fm.get("sources") or [] if s.get("predicate") == "linkedin"]
    assert fact_sources.is_tombstoned(fm, "https://www.linkedin.com/in/sam-okafor", "linkedin")
    claims = [c for c in parse_claims(page.body) if c.observer == linkedin_people.OBSERVER]
    assert claims and all(c.valid_to for c in claims)                                  # closed by id, kept as history
    record = w.records(fm)[-1]
    assert record["state"] == "undone" and record["undone_on"]
    assert merge_rejections.refused_by_name(world.mem, "sam", "Sam Okafor")
    message = world.git("log", "-1", "--format=%B")
    assert message.startswith("Undid an arrival join") and "Cicada-Author: user" in message
    for sha in record["commits"]:
        assert f"Undoes: {sha}" in message
    assert "Okafor" not in message and out["commit"] == world.head()


def test_after_not_them_no_night_joins_that_pair_again(world):
    world.night()
    w.undo(world.mem, "sam", before=None)
    head = world.head()
    world.night()
    assert world.head() == head
    assert aj.load_report(world.mem.name)["items"][0]["reason"] == "history"


def test_the_history_marks_the_join_undoable_until_it_is_taken_back(world):
    world.night()
    rows, _ = asyncio.run(page_history.page("sam", world.mem))
    joins = [r for r in rows if r.join == "arrival"]
    assert len(joins) == 1 and joins[0].undoable and joins[0].trigger == "sleep/arrival-join"
    assert joins[0].joined_as == "Sam Okafor"
    w.undo(world.mem, "sam", before=None)
    rows, _ = asyncio.run(page_history.page("sam", world.mem))
    assert next(r for r in rows if r.join == "arrival").undoable is False
    assert next(r for r in rows if r.join == "arrival").joined_as == "Sam Okafor"     # still says whom it was, once taken back
    assert any(r.join == "undo" for r in rows)


def test_an_undo_with_nothing_to_undo_or_twice_says_so_and_writes_nothing(world):
    with pytest.raises(w.UndoError) as none:
        w.undo(world.mem, "sam", before=None)
    assert none.value.status == 404
    with pytest.raises(w.UndoError) as missing:
        w.undo(world.mem, "ghost", before=None)
    assert missing.value.status == 404
    world.night()
    w.undo(world.mem, "sam", before=None)
    head = world.head()
    with pytest.raises(w.UndoError) as again:
        w.undo(world.mem, "sam", before=None)
    assert again.value.status == 409 and "already" in str(again.value) and world.head() == head


def test_if_the_person_took_the_link_since_the_undo_writes_nothing_and_says_what_is_left(world):
    world.night()
    page = world.page()
    fm = dict(page.frontmatter)
    fm["sources"] = [{**s, "accepted": True} if s.get("predicate") == "linkedin" else s for s in fm["sources"]]
    markdown_parser.write(world.mem / "entities" / "sam.md", fm, page.body)
    head, snapshot = world.head(), (world.mem / "entities" / "sam.md").read_text()
    with pytest.raises(w.UndoError) as refused:
        w.undo(world.mem, "sam", before=None)
    record = w.latest(fm, w.JOINED)
    text = str(refused.value)
    assert refused.value.status == 409 and "Nothing was undone" in text and "the name is on the page" in text
    assert record["sources"][0] in text                                                 # the link, by its id
    assert (world.mem / "entities" / "sam.md").read_text() == snapshot and world.head() == head
    assert "Okafor" not in text and "linkedin.com" not in text


def test_if_the_person_changed_the_name_since_the_undo_writes_nothing(world):
    world.night()
    page = world.page()
    fm = {**page.frontmatter, "aliases": ["Samuel Okafor"]}
    markdown_parser.write(world.mem / "entities" / "sam.md", fm, page.body)
    with pytest.raises(w.UndoError) as refused:
        w.undo(world.mem, "sam", before=None)
    assert "changed or taken off by you" in str(refused.value)
    assert world.page().frontmatter["aliases"] == ["Samuel Okafor"]


def test_not_them_takes_the_contacts_entries_and_face_back_and_the_next_sync_never_returns_them(tmp_path, monkeypatch):
    import base64

    w2 = World(tmp_path, monkeypatch, scene(conns=[], cards=[("Sam", "Okafor", CONNECTED)]))
    contacts_local.save_waiting(w2.mem.name, [{"id": "card-0", "given_name": "Sam", "family_name": "Okafor",
                                               "has_organization": True, "photo_b64": base64.b64encode(JPEG).decode()}])
    w2.night()
    assert contacts_local.photo_path(w2.mem.name, "sam", "jpg").exists()
    w.undo(w2.mem, "sam", before=None)
    fm = w2.page().frontmatter
    assert not [s for s in fm.get("sources") or [] if str(s.get("ref")).startswith("addressbook://")]
    assert "contacts_photo" not in fm and not contacts_local.photo_path(w2.mem.name, "sam", "jpg").exists()
    assert ("sam", "addressbook://card-0", "works-at") in contacts_local.load_refused(w2.mem)
    # the next sync: the card matches no page again and waits; the page takes nothing
    contacts_local.sync(w2.mem, {"contacts": [{"id": "card-0", "given_name": "Sam", "family_name": "Okafor", "has_organization": True}]})
    assert not [s for s in w2.page().frontmatter.get("sources") or [] if str(s.get("ref")).startswith("addressbook://")]
    assert [c["id"] for c in contacts_local.load_waiting(w2.mem.name)] == ["card-0"]


def test_a_later_page_of_the_full_name_can_never_re_join_the_pair(world):
    world.night()
    w.undo(world.mem, "sam", before=None)
    assert merge_rejections.arrival_refusals(world.mem)                     # no page of the name yet: kept by hash
    (world.mem / "entities" / "sam-okafor.md").write_text("---\nname: Sam Okafor\ntype: person\nstatus: active\n---\n## Summary\nx\n")
    bank_index.invalidate(world.mem)
    asyncio.run(sleep_cycle._arrival_refusals_safely(world.mem))
    assert merge_rejections.is_rejected(world.mem, "sam", "sam-okafor")      # every joiner honours a refused pair of pages
    assert merge_rejections.arrival_refusals(world.mem) == []
    assert "Arrival join refusals" in world.subjects()[0]
    assert ("sam", "sam-okafor") in merge_rejections.kept_apart(world.mem)


def test_the_refusal_is_readable_by_name_before_any_page_exists(world):
    world.night()
    w.undo(world.mem, "sam", before=None)
    assert merge_rejections.refused_by_name(world.mem, "sam", "Sam Okafor")
    assert not merge_rejections.refused_by_name(world.mem, "sam", "Sam Berg")
    assert not merge_rejections.refused_by_name(world.mem, "other", "Sam Okafor")
    text = (world.mem / "_merge_rejected.yaml").read_text()
    assert "Okafor" not in text and "okafor" not in text.lower()          # by a hash, never the name


def test_the_other_joiners_files_survive_a_refusal_written_beside_them(world):
    merge_rejections.add_rejected(world.mem, "a", "b")
    merge_rejections.add_arrival_refusal(world.mem, "sam", "k" * 16, on="2026-11-12")
    merge_rejections.add_rejected(world.mem, "c", "d")
    assert merge_rejections.load_rejected(world.mem) == {("a", "b"), ("c", "d")}
    assert [r["key"] for r in merge_rejections.arrival_refusals(world.mem)] == ["k" * 16]


# --- the route -------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(world.mem))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_route_says_not_them_once_and_a_sentence_after(world, client):
    world.night()
    ok = client.post("/entities/sam/arrival-join/undo")
    assert ok.status_code == 200, ok.text
    assert ok.json()["kind"] == "arrival-undo" and ok.json()["commit"] == world.head()
    again = client.post("/entities/sam/arrival-join/undo")
    assert again.status_code == 409 and "already" in again.json()["detail"]
    assert client.post("/entities/ghost/arrival-join/undo").status_code == 404


def test_the_route_is_forwarded_by_a_replica_like_every_page_write():
    from api.services import replica_routes

    assert replica_routes.ROUTES["POST /entities/{entity_id}/arrival-join/undo"] == replica_routes.FORWARD


def test_the_connections_list_shows_the_row_a_join_stands_on(world):
    world.night()
    rows = linkedin_people.list_rows(world.mem, world.mem.name)["rows"]
    assert rows[0]["page"] == "sam"
    joined = w.joined_for(world.mem)
    assert rows[0]["id"] in joined and joined[rows[0]["id"]]["delta"] == 2


def test_the_connections_route_carries_the_join_and_the_agent_door_only_ids_and_days(world, client):
    world.night()
    body = client.get("/sources/linkedin-connections/list").json()
    row = body["rows"][0]
    assert row["page"] == "sam" and row["joined"]["page"] == "sam" and row["joined"]["delta"] == 2
    assert row["joined"]["holderDay"] == battery.d(0)
    client.post("/entities/sam/arrival-join/undo")
    assert client.get("/sources/linkedin-connections/list").json()["rows"][0]["joined"] is None


def test_the_agent_door_names_the_page_a_row_was_joined_to_by_id_and_days(world, monkeypatch):
    from _stdio_server import stdio_server

    world.night()
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: world.mem)
    out = server.handle_tool("cicada_linkedin_connections", {"since": "2026-10-01", "until": "2026-12-31"})
    assert "joined to the first-name page `sam` (2 days from" in out
